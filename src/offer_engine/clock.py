"""The Simulation Clock (ADR 0003): one stored simulated time that moves only when advanced."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

# Generated history ends here and the live world starts here.
START = datetime(2026, 12, 1, 0, 0)


def now(conn: sqlite3.Connection) -> datetime:
    row = conn.execute("SELECT now FROM clock WHERE id = 1").fetchone()
    return datetime.fromisoformat(row[0]) if row else START


def set_now(conn: sqlite3.Connection, at: datetime) -> None:
    if at.tzinfo is not None:
        raise ValueError("Simulation Clock times are naive simulated IST; got a timezone-aware datetime")
    conn.execute(
        "INSERT INTO clock (id, now) VALUES (1, ?) ON CONFLICT (id) DO UPDATE SET now = excluded.now",
        (at.isoformat(timespec="seconds"),),
    )
    conn.commit()


def advance(conn: sqlite3.Connection, hours: int) -> datetime:
    if hours < 0:
        raise ValueError("the Simulation Clock only moves forward")
    new_now = now(conn) + timedelta(hours=hours)
    set_now(conn, new_now)
    return new_now
