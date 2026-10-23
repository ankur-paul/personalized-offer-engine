"""Load what the decision pipeline may know about a Customer at `now` (observable tables only, never `sim_*`)."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta

from offer_engine.domain import (
    ChatKind,
    ChatLink,
    Customer,
    CustomerState,
    Event,
    OfferStatus,
    OfferType,
    PastOffer,
)

EVENT_DAYS = 180

# SQLite's default limit on `?` parameters is well above this.
CHUNK = 500


def population_filter(alias: str = "") -> str:
    """SQL condition that leaves Tester copies out of population metrics (PLAN "Assumed › Outcomes"), e.g.
    `f"SELECT COUNT(*) FROM customers c WHERE {population_filter('c')}"`."""
    return f"{alias}.is_tester_copy = 0" if alias else "is_tester_copy = 0"


def load_customer_state(conn: sqlite3.Connection, customer_id: str, now: datetime) -> CustomerState:
    """Raises KeyError if the Customer doesn't exist."""
    states = load_customer_states(conn, [customer_id], now)
    if customer_id not in states:
        raise KeyError(f"no Customer {customer_id}")
    return states[customer_id]


def load_customer_states(
    conn: sqlite3.Connection, ids: Iterable[str], now: datetime
) -> dict[str, CustomerState]:
    """States for the Customers in `ids` that exist: events of the last 180 days and every Offer created by `now`."""
    ids = list(dict.fromkeys(ids))
    states: dict[str, CustomerState] = {}
    for i in range(0, len(ids), CHUNK):
        states.update(_load_chunk(conn, ids[i : i + CHUNK], now))
    return states


def _load_chunk(conn: sqlite3.Connection, ids: list[str], now: datetime) -> dict[str, CustomerState]:
    marks = ",".join("?" * len(ids))
    at_now = now.isoformat(timespec="seconds")
    since = (now - timedelta(days=EVENT_DAYS)).isoformat(timespec="seconds")

    customers = {
        row["id"]: _customer(row)
        for row in conn.execute(f"SELECT * FROM customers WHERE id IN ({marks})", ids)
    }
    events: dict[str, list[Event]] = defaultdict(list)
    query = (
        "SELECT customer_id, at, kind, category, product_id, amount, offer_id FROM events "
        f"WHERE customer_id IN ({marks}) AND at >= ? AND at <= ? ORDER BY at, id"
    )
    for row in conn.execute(query, [*ids, since, at_now]):
        events[row["customer_id"]].append(
            Event(
                row["customer_id"],
                datetime.fromisoformat(row["at"]),
                row["kind"],
                row["category"],
                row["product_id"],
                row["amount"],
                row["offer_id"],
            )
        )
    offers: dict[str, list[PastOffer]] = defaultdict(list)
    query = (
        "SELECT id, customer_id, offer_type, category, status, created_at, expires_at, redeemed_at FROM offers "
        f"WHERE customer_id IN ({marks}) AND created_at <= ? ORDER BY created_at, id"
    )
    for row in conn.execute(query, [*ids, at_now]):
        offers[row["customer_id"]].append(
            PastOffer(
                id=row["id"],
                offer_type=OfferType(row["offer_type"]),
                category=row["category"],
                status=OfferStatus(row["status"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                expires_at=datetime.fromisoformat(row["expires_at"]),
                redeemed_at=_time(row["redeemed_at"]),
            )
        )
    chats = {
        row["customer_id"]: ChatLink(row["customer_id"], row["chat_id"], ChatKind(row["kind"]))
        for row in conn.execute(f"SELECT * FROM chats WHERE customer_id IN ({marks})", ids)
    }
    return {
        cid: CustomerState(customer, tuple(events[cid]), tuple(offers[cid]), chats.get(cid))
        for cid, customer in customers.items()
    }


def _customer(row: sqlite3.Row) -> Customer:
    return Customer(
        id=row["id"],
        signup_at=datetime.fromisoformat(row["signup_at"]),
        city_tier=row["city_tier"],
        device=row["device"],
        channel=row["channel"],
        loyalty_tier=row["loyalty_tier"],
        points_balance=row["points_balance"],
        points_expire_at=_time(row["points_expire_at"]),
        opted_out=bool(row["opted_out"]),
        is_tester_copy=bool(row["is_tester_copy"]),
        source_customer_id=row["source_customer_id"],
    )


def _time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
