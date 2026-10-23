"""Emergency withdraw (PLAN §3.3): every outstanding live Offer becomes `withdrawn`, and each chat that has seen
its Offer Card is told the code no longer works."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from offer_engine.budget import OUTSTANDING
from offer_engine.domain import OfferSource, OfferStatus

NOTICE = "This offer has been withdrawn: {code}. Sorry for the change."


@dataclass(frozen=True)
class Withdrawal:
    author: str
    offers: int
    created_at: datetime  # simulated time
    saved_at: datetime  # wall-clock time, UTC


def withdraw_outstanding(conn: sqlite3.Connection, now: datetime, author: str) -> int:
    """Withdraw every unexpired `queued`, `sent` or `claimed` live Offer and log who did it. Returns the count.

    Queued Offers get no notice: their card was never sent, and the Offer Bot only sends queued ones.
    """
    at = now.isoformat(timespec="seconds")
    rows = _outstanding(conn, now)
    conn.executemany(
        "UPDATE offers SET status = ? WHERE id = ?", [(OfferStatus.WITHDRAWN, row["id"]) for row in rows]
    )
    conn.executemany(
        "INSERT INTO outbox (chat_id, text, created_at) VALUES (?, ?, ?)",
        [
            (row["chat_id"], NOTICE.format(code=row["code"]), at)
            for row in rows
            if row["chat_id"] is not None and row["status"] != OfferStatus.QUEUED
        ],
    )
    conn.execute(
        "INSERT INTO withdrawals (author, offers, created_at, saved_at) VALUES (?, ?, ?, ?)",
        (author, len(rows), at, datetime.now(UTC).isoformat(timespec="seconds")),
    )
    conn.commit()
    return len(rows)


def count_outstanding(conn: sqlite3.Connection, now: datetime) -> int:
    """How many Offers `withdraw_outstanding` would withdraw at `now`."""
    return len(_outstanding(conn, now))


def _outstanding(conn: sqlite3.Connection, now: datetime) -> list[sqlite3.Row]:
    marks = ",".join("?" * len(OUTSTANDING))
    return conn.execute(
        "SELECT o.id, o.code, o.status, ch.chat_id FROM offers o LEFT JOIN chats ch ON ch.customer_id = o.customer_id"
        f" WHERE o.source = ? AND o.status IN ({marks}) AND o.expires_at > ? ORDER BY o.id",
        (OfferSource.LIVE, *OUTSTANDING, now.isoformat(timespec="seconds")),
    ).fetchall()


def list_withdrawals(conn: sqlite3.Connection) -> list[Withdrawal]:
    """Newest first."""
    return [
        Withdrawal(
            author=row["author"],
            offers=row["offers"],
            created_at=datetime.fromisoformat(row["created_at"]),
            saved_at=datetime.fromisoformat(row["saved_at"]),
        )
        for row in conn.execute("SELECT * FROM withdrawals ORDER BY id DESC")
    ]
