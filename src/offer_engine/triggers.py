"""Event Triggers (PLAN §3.1), run by the day-step every simulated hour: cart abandoned, points expiring soon, long
gap since the last order, first order delivered.

A Trigger only asks the pipeline; Rules still decide whether anything is sent. Each hit carries a key naming its
underlying event, and `trigger_log` makes sure one event fires once, however often a detector sees it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from offer_engine import pipeline
from offer_engine.domain import Decision, Event, TriggerKind
from offer_engine.rules_store import current_rules

HOUR = timedelta(hours=1)
FIRST = "first"


@dataclass(frozen=True)
class Hit:
    customer_id: str
    kind: TriggerKind
    key: str


# --- Detectors: pure, on what the queries below hand them --------------------------------------


def cart_abandoned(new_events: Iterable[Event]) -> list[Hit]:
    """Each new `cart_abandoned` event, keyed by its time."""
    return [
        Hit(e.customer_id, TriggerKind.CART_ABANDONED, _iso(e.at))
        for e in new_events
        if e.kind == "cart_abandoned"
    ]


def first_order_delivered(new_events: Iterable[Event], first_delivery: dict[str, datetime]) -> list[Hit]:
    """A new `delivered` event that is the Customer's earliest (`first_delivery` maps Customer → its time)."""
    hits = {
        e.customer_id: Hit(e.customer_id, TriggerKind.FIRST_ORDER_DELIVERED, FIRST)
        for e in new_events
        if e.kind == "delivered" and first_delivery.get(e.customer_id) == e.at
    }
    return list(hits.values())


def points_expiring(
    balances: Iterable[tuple[str, int, datetime | None]], now: datetime, warning_days: int
) -> list[Hit]:
    """Customers with points that expire within `warning_days` of `now`, keyed by the expiry date."""
    horizon = now + timedelta(days=warning_days)
    return [
        Hit(customer_id, TriggerKind.POINTS_EXPIRING, expires_at.date().isoformat())
        for customer_id, balance, expires_at in balances
        if balance > 0 and expires_at is not None and now < expires_at <= horizon
    ]


def long_gap(last_orders: Iterable[tuple[str, datetime]], now: datetime, gap_days: int) -> list[Hit]:
    """Customers whose time since their last order reaches `gap_days` in the hour ending `now`, keyed by that
    order's time."""
    gap = timedelta(days=gap_days)
    return [
        Hit(customer_id, TriggerKind.LONG_GAP, _iso(last))
        for customer_id, last in last_orders
        if now - HOUR < last + gap <= now
    ]


# --- Running them ------------------------------------------------------------------------------


def on_hour(conn: sqlite3.Connection, now: datetime, new_events: list[Event], report: Any) -> None:
    """`new_events` are the events inserted this hour, so Triggers needn't re-scan the table. `report` is the
    day-step's DayReport; each Decision counts as `decisions.<trigger>`."""
    for hit in detect(conn, now, new_events):
        if fire(conn, hit, now) is not None:
            report.counts[f"decisions.{hit.kind}"] += 1


def detect(conn: sqlite3.Connection, now: datetime, new_events: list[Event]) -> list[Hit]:
    """Every Trigger hit at `now`, event Triggers first. May include hits that already fired."""
    _, rules = current_rules(conn)
    warning, gap = rules.points_expiry_warning_days, rules.long_gap_days
    return (
        cart_abandoned(new_events)
        + first_order_delivered(new_events, _first_deliveries(conn, new_events))
        + points_expiring(_expiring_balances(conn, now, warning), now, warning)
        + long_gap(_last_orders(conn, now, gap), now, gap)
    )


def fire(conn: sqlite3.Connection, hit: Hit, now: datetime) -> Decision | None:
    """Log the hit and run the pipeline; None if this hit's event already fired. The log row commits with the
    Decision, so a Decision that fails leaves the event free to fire again."""
    claimed = conn.execute(
        "INSERT OR IGNORE INTO trigger_log (customer_id, kind, key, at) VALUES (?, ?, ?, ?)",
        (hit.customer_id, hit.kind, hit.key, _iso(now)),
    ).rowcount
    if not claimed:
        return None
    try:
        return pipeline.decide(conn, hit.customer_id, hit.kind, now)
    except Exception:
        conn.rollback()
        raise


def _first_deliveries(conn: sqlite3.Connection, new_events: list[Event]) -> dict[str, datetime]:
    ids = sorted({e.customer_id for e in new_events if e.kind == "delivered"})
    if not ids:
        return {}
    rows = conn.execute(
        "SELECT customer_id, MIN(at) FROM events WHERE kind = 'delivered' "
        f"AND customer_id IN ({','.join('?' * len(ids))}) GROUP BY customer_id",
        ids,
    )
    return {row[0]: datetime.fromisoformat(row[1]) for row in rows}


def _expiring_balances(
    conn: sqlite3.Connection, now: datetime, warning_days: int
) -> list[tuple[str, int, datetime]]:
    """Candidates whose current expiry date hasn't fired yet."""
    rows = conn.execute(
        "SELECT c.id, c.points_balance, c.points_expire_at FROM customers c WHERE c.points_balance > 0 "
        "AND c.points_expire_at > ? AND c.points_expire_at <= ? AND NOT EXISTS (SELECT 1 FROM trigger_log l "
        "WHERE l.customer_id = c.id AND l.kind = ? AND l.key = substr(c.points_expire_at, 1, 10))",
        (_iso(now), _iso(now + timedelta(days=warning_days)), TriggerKind.POINTS_EXPIRING),
    )
    return [(row[0], row[1], datetime.fromisoformat(row[2])) for row in rows]


def _last_orders(conn: sqlite3.Connection, now: datetime, gap_days: int) -> list[tuple[str, datetime]]:
    """Orders placed `gap_days` ago, within the hour, that are still their Customer's latest."""
    gap = timedelta(days=gap_days)
    rows = conn.execute(
        "SELECT e.customer_id, e.at FROM events e WHERE e.kind = 'order' AND e.at > ? AND e.at <= ? "
        "AND NOT EXISTS (SELECT 1 FROM events o WHERE o.customer_id = e.customer_id AND o.kind = 'order' "
        "AND o.at > e.at)",
        (_iso(now - gap - HOUR), _iso(now - gap)),
    )
    return [(row[0], datetime.fromisoformat(row[1])) for row in rows]


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="seconds")
