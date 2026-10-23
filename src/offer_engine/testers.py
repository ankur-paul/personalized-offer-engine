"""Tester copies (PLAN §4.1, QnA Q16, Q42): a human playing a showcase Customer gets their own copy of it, so two
Testers playing the same Customer don't use up each other's caps.

A copy is `<id>-t<telegram user id>` with `is_tester_copy = 1`. It holds the source's Customer row (points
included), its last 180 days of events and every past Offer that is finished or expired, whatever its age, since the
pipeline reads all of them (`customers.load_customer_states`). So the engine decides for the copy as it would for the
source. Offers still open stay behind: their outcomes belong to the source. Copies have no `sim_*` rows:
they do nothing organic (T17), and their outcomes use the source's Ground Truth through `source_customer_id` (T18).

A chat plays one Customer at a time. The copy a Tester switches away from is opted out, so nothing keeps sending
Offers to a Customer nobody plays; picking it again turns them back on.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from offer_engine import clock
from offer_engine.customers import EVENT_DAYS
from offer_engine.domain import ChatKind, OfferStatus
from offer_engine.pipeline import new_code

# Offers that can't change any more, so a copy may carry them without inheriting an outcome. An Offer past its
# expiry is finished too, whatever its status says.
FINISHED = (OfferStatus.REDEEMED, OfferStatus.EXPIRED, OfferStatus.DISMISSED, OfferStatus.WITHDRAWN)


def copy_id(source_customer_id: str, telegram_user_id: int) -> str:
    return f"{source_customer_id}-t{telegram_user_id}"


def create_tester_copy(
    conn: sqlite3.Connection, source_customer_id: str, telegram_user_id: int, chat_id: int | None = None
) -> str:
    """The Tester's copy of `source_customer_id`, created on first pick, linked to `chat_id` (default: the user's
    private chat) and opted in. Raises KeyError for an unknown Customer, ValueError for a Tester copy."""
    source = conn.execute(
        "SELECT is_tester_copy FROM customers WHERE id = ?", (source_customer_id,)
    ).fetchone()
    if source is None:
        raise KeyError(f"no Customer {source_customer_id}")
    if source["is_tester_copy"]:
        raise ValueError(f"{source_customer_id} is a Tester copy")
    chat_id = telegram_user_id if chat_id is None else chat_id
    cid = copy_id(source_customer_id, telegram_user_id)
    now = clock.now(conn)
    with conn:
        if conn.execute("SELECT 1 FROM customers WHERE id = ?", (cid,)).fetchone() is None:
            _copy(conn, source_customer_id, cid, now)
        _link(conn, cid, chat_id, now)
    return cid


def played_by(conn: sqlite3.Connection, chat_id: int) -> str | None:
    """The Tester copy this chat plays, if any."""
    row = conn.execute(
        "SELECT ch.customer_id FROM chats ch JOIN customers c ON c.id = ch.customer_id"
        " WHERE ch.chat_id = ? AND ch.kind = ? AND c.is_tester_copy = 1",
        (chat_id, ChatKind.TESTER),
    ).fetchone()
    return row[0] if row else None


def _copy(conn: sqlite3.Connection, source: str, cid: str, now: datetime) -> None:
    columns = _columns(conn, "customers", skip={"id", "opted_out", "is_tester_copy", "source_customer_id"})
    conn.execute(
        f"INSERT INTO customers (id, opted_out, is_tester_copy, source_customer_id, {columns})"
        f" SELECT ?, 0, 1, id, {columns} FROM customers WHERE id = ?",
        (cid, source),
    )
    since, at_now = _iso(now - timedelta(days=EVENT_DAYS)), _iso(now)

    offer_ids: dict[int, int] = {}
    columns = _columns(conn, "offers", skip={"id", "code", "customer_id"})
    marks = ",".join("?" * len(FINISHED))
    rows = conn.execute(
        f"SELECT id FROM offers WHERE customer_id = ? AND created_at <= ?"
        f" AND (status IN ({marks}) OR expires_at <= ?) ORDER BY id",
        (source, at_now, *FINISHED, at_now),
    ).fetchall()
    for (old_id,) in rows:
        while True:
            try:
                cur = conn.execute(
                    f"INSERT INTO offers (code, customer_id, {columns}) SELECT ?, ?, {columns} FROM offers"
                    " WHERE id = ?",
                    (new_code(), cid, old_id),
                )
                break
            except sqlite3.IntegrityError as exc:
                if "offers.code" not in str(exc):
                    raise
        offer_ids[old_id] = cur.lastrowid

    events = conn.execute(
        "SELECT at, kind, category, product_id, amount, offer_id FROM events"
        " WHERE customer_id = ? AND at >= ? AND at <= ? ORDER BY at, id",
        (source, since, at_now),
    ).fetchall()
    conn.executemany(
        "INSERT INTO events (customer_id, at, kind, category, product_id, amount, offer_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(cid, *e[:5], offer_ids.get(e["offer_id"])) for e in events],
    )


def _link(conn: sqlite3.Connection, cid: str, chat_id: int, now: datetime) -> None:
    """Make `chat_id` play `cid` only. Copies it played before are opted out; other Customers are just unlinked."""
    for (other,) in conn.execute(
        "SELECT ch.customer_id FROM chats ch JOIN customers c ON c.id = ch.customer_id"
        " WHERE ch.chat_id = ? AND ch.customer_id != ? AND c.is_tester_copy = 1",
        (chat_id, cid),
    ).fetchall():
        _set_opted_out(conn, other, True, now)
    conn.execute("DELETE FROM chats WHERE chat_id = ? AND customer_id != ?", (chat_id, cid))
    conn.execute(
        "INSERT INTO chats (customer_id, chat_id, kind) VALUES (?, ?, ?)"
        " ON CONFLICT (customer_id) DO UPDATE SET chat_id = excluded.chat_id, kind = excluded.kind",
        (cid, chat_id, ChatKind.TESTER),
    )
    _set_opted_out(conn, cid, False, now)


def _set_opted_out(conn: sqlite3.Connection, customer_id: str, out: bool, now: datetime) -> None:
    """Opt in or out, with the event, if that changes anything. Opting out withdraws queued Offers, as Stop does."""
    changed = conn.execute(
        "UPDATE customers SET opted_out = ? WHERE id = ? AND opted_out != ?",
        (int(out), customer_id, int(out)),
    ).rowcount
    if not changed:
        return
    if out:
        conn.execute(
            "UPDATE offers SET status = ? WHERE customer_id = ? AND status = ?",
            (OfferStatus.WITHDRAWN, customer_id, OfferStatus.QUEUED),
        )
    conn.execute(
        "INSERT INTO events (customer_id, at, kind) VALUES (?, ?, ?)",
        (customer_id, _iso(now), "opted_out" if out else "opted_in"),
    )


def _columns(conn: sqlite3.Connection, table: str, skip: set[str]) -> str:
    return ", ".join(
        row["name"] for row in conn.execute(f"PRAGMA table_info({table})") if row["name"] not in skip
    )


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="seconds")
