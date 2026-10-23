"""`sim_pending_events`: organic events drawn but not yet due. The generated history hands its scheduled deliveries
and returns to the live world here."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING

from offer_engine.domain import Event

if TYPE_CHECKING:
    from offer_engine.sim.generate import GenContext


def pending(conn: sqlite3.Connection, drawn: bool, before: datetime, delete: bool = False) -> list[Event]:
    rows = conn.execute(
        "SELECT id, customer_id, at, kind, category, product_id, amount, offer_id FROM sim_pending_events "
        "WHERE drawn = ? AND at < ? ORDER BY at, id",
        (int(drawn), _iso(before)),
    ).fetchall()
    if delete and rows:
        conn.execute("DELETE FROM sim_pending_events WHERE drawn = ? AND at < ?", (int(drawn), _iso(before)))
    return [
        Event(
            row["customer_id"],
            datetime.fromisoformat(row["at"]),
            row["kind"],
            row["category"],
            row["product_id"],
            row["amount"],
            row["offer_id"],
        )
        for row in rows
    ]


def add_pending(conn: sqlite3.Connection, events: list[Event], drawn: bool) -> None:
    conn.executemany(
        "INSERT INTO sim_pending_events (customer_id, at, kind, category, product_id, amount, offer_id, drawn) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (e.customer_id, _iso(e.at), e.kind, e.category, e.product_id, e.amount, e.offer_id, int(drawn))
            for e in events
        ],
    )


def save_scheduled(ctx: GenContext) -> None:
    """Generate step: keep the deliveries and returns the history scheduled past its end for the live world."""
    add_pending(ctx.conn, [e for events in ctx.scheduled.values() for e in events], drawn=False)


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="seconds")
