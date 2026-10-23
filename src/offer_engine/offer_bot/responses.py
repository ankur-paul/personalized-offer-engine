"""What a Customer's Claim, Not now, Stop and `/start` do to the database (PLAN §4.1, §3.3). Each function commits
and returns the reply text. The chat linked to an Offer's Customer is the only one that may act on it."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from offer_engine import clock
from offer_engine.domain import OfferStatus

NOT_LINKED = "This chat isn't linked to a Customer."
NOT_ACTIVE = "That code isn't active any more."
NOT_YOURS = "That code isn't yours."
DISMISSED = "No problem. We'll ease off for a bit."
STOPPED = "You won't get any more offers. Send /start any time to turn them back on."
RESTARTED = "Welcome back! You'll get offers again."
ALREADY_ON = "You're already getting offers."


def claim(conn: sqlite3.Connection, code: str, chat_id: int) -> str:
    """A sent Offer becomes claimed. Claiming it again repeats the reply."""
    offer, refusal = _own_offer(conn, code, chat_id)
    if refusal:
        return refusal
    if offer["status"] == OfferStatus.SENT:
        _set_status(conn, offer, OfferStatus.CLAIMED, "offer_claimed")
    elif offer["status"] != OfferStatus.CLAIMED:
        return NOT_ACTIVE
    expires = datetime.fromisoformat(offer["expires_at"])
    return f"Claimed! Your code is {offer['code']}. It's valid until {expires.day} {expires:%b, %H:%M}."


def dismiss(conn: sqlite3.Connection, code: str, chat_id: int) -> str:
    """A sent Offer becomes dismissed, which counts towards the Fatigue Pause. Dismissing it again repeats the
    reply; a claimed one stays claimed."""
    offer, refusal = _own_offer(conn, code, chat_id)
    if refusal:
        return refusal
    if offer["status"] == OfferStatus.SENT:
        _set_status(conn, offer, OfferStatus.DISMISSED, "offer_dismissed")
    elif offer["status"] == OfferStatus.CLAIMED:
        return f"You've already claimed {offer['code']}."
    elif offer["status"] != OfferStatus.DISMISSED:
        return NOT_ACTIVE
    return DISMISSED


def stop(conn: sqlite3.Connection, chat_id: int) -> str:
    """Opt out every Customer linked to the chat and withdraw their queued Offers. Sent ones stay usable."""
    customers = _linked(conn, chat_id)
    if not customers:
        return NOT_LINKED
    now = _now(conn)
    for customer_id, opted_out in customers:
        if opted_out:
            continue
        conn.execute("UPDATE customers SET opted_out = 1 WHERE id = ?", (customer_id,))
        conn.execute(
            "UPDATE offers SET status = ? WHERE customer_id = ? AND status = ?",
            (OfferStatus.WITHDRAWN, customer_id, OfferStatus.QUEUED),
        )
        _event(conn, customer_id, now, "opted_out")
    conn.commit()
    return STOPPED


def restart(conn: sqlite3.Connection, chat_id: int) -> str:
    """Opt back in every opted-out Customer linked to the chat."""
    customers = _linked(conn, chat_id)
    if not customers:
        return NOT_LINKED
    opted_out = [customer_id for customer_id, out in customers if out]
    if not opted_out:
        return ALREADY_ON
    now = _now(conn)
    for customer_id in opted_out:
        conn.execute("UPDATE customers SET opted_out = 0 WHERE id = ?", (customer_id,))
        _event(conn, customer_id, now, "opted_in")
    conn.commit()
    return RESTARTED


def _own_offer(conn: sqlite3.Connection, code: str, chat_id: int) -> tuple[sqlite3.Row | None, str | None]:
    """The Offer with `code` if this chat may act on it and it hasn't expired, else the refusal text."""
    offer = conn.execute(
        "SELECT o.*, c.chat_id FROM offers o LEFT JOIN chats c ON c.customer_id = o.customer_id"
        " WHERE o.code = ?",
        (code.strip().upper(),),
    ).fetchone()
    if offer is None or offer["status"] == OfferStatus.QUEUED:
        return None, NOT_ACTIVE
    if offer["chat_id"] != chat_id:
        return None, NOT_YOURS
    if datetime.fromisoformat(offer["expires_at"]) <= clock.now(conn):
        return None, NOT_ACTIVE
    return offer, None


def _set_status(conn: sqlite3.Connection, offer: sqlite3.Row, status: OfferStatus, kind: str) -> None:
    conn.execute("UPDATE offers SET status = ? WHERE id = ?", (status, offer["id"]))
    _event(conn, offer["customer_id"], _now(conn), kind, offer["category"], offer["id"])
    conn.commit()


def _linked(conn: sqlite3.Connection, chat_id: int) -> list[tuple[str, bool]]:
    rows = conn.execute(
        "SELECT c.id, c.opted_out FROM chats ch JOIN customers c ON c.id = ch.customer_id WHERE ch.chat_id = ?",
        (chat_id,),
    )
    return [(row[0], bool(row[1])) for row in rows]


def _event(
    conn: sqlite3.Connection,
    customer_id: str,
    at: str,
    kind: str,
    category: str | None = None,
    offer_id: int | None = None,
) -> None:
    conn.execute(
        "INSERT INTO events (customer_id, at, kind, category, offer_id) VALUES (?, ?, ?, ?, ?)",
        (customer_id, at, kind, category, offer_id),
    )


def _now(conn: sqlite3.Connection) -> str:
    return clock.now(conn).isoformat(timespec="seconds")
