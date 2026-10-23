"""Daily Sweep (PLAN §3.1, "Assumed › Deciding"), called by the day-step every simulated hour. At 10:00 simulated
time it runs the decision pipeline for every Customer (win-back and lapse), chat-attached ones first so the weekly
budget can't run out before the live demo Customers are considered.
"""

from __future__ import annotations

import random
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from offer_engine import pipeline
from offer_engine.domain import TriggerKind

SWEEP_HOUR = 10
SKIP_WINDOW = timedelta(hours=24)


def on_hour(conn: sqlite3.Connection, now: datetime, report: Any) -> None:
    """`report` is the day-step's DayReport; add counts to `report.counts`."""
    if now.hour == SWEEP_HOUR:
        report.counts.update(sweep(conn, now))


def sweep(conn: sqlite3.Connection, now: datetime) -> Counter[str]:
    """Decide for every Customer without a Decision in the last 24 simulated hours. Counts `sweep.offer`,
    `sweep.no_offer`, `sweep.skipped` and `sweep.binding.<Binding Rule>`."""
    counts: Counter[str] = Counter()
    recent = _decided_since(conn, now - SKIP_WINDOW, now)
    order = [cid for cid in sweep_order(conn, now) if cid not in recent]
    counts["sweep.skipped"] = len(recent)
    for decision in pipeline.decide_many(conn, order, TriggerKind.DAILY_SWEEP, now):
        counts["sweep.offer" if decision.offer_id is not None else "sweep.no_offer"] += 1
        if decision.binding_rule:
            counts[f"sweep.binding.{decision.binding_rule}"] += 1
    return +counts


def sweep_order(conn: sqlite3.Connection, now: datetime) -> list[str]:
    """Chat-attached Customers in ID order, then the rest shuffled by a seed derived from the simulated date."""
    rows = conn.execute(
        "SELECT c.id, ch.customer_id IS NOT NULL FROM customers c LEFT JOIN chats ch ON ch.customer_id = c.id "
        "ORDER BY c.id"
    ).fetchall()
    chat = [cid for cid, attached in rows if attached]
    rest = [cid for cid, attached in rows if not attached]
    random.Random(now.date().isoformat()).shuffle(rest)
    return chat + rest


def _decided_since(conn: sqlite3.Connection, since: datetime, now: datetime) -> set[str]:
    """Customers with a Decision after `since`, so yesterday's 10:00 sweep doesn't block today's."""
    rows = conn.execute(
        "SELECT DISTINCT customer_id FROM decisions WHERE at > ? AND at <= ?",
        (since.isoformat(timespec="seconds"), now.isoformat(timespec="seconds")),
    )
    return {row[0] for row in rows}
