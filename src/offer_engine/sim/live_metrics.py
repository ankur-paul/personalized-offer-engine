"""What the live world has done since the clock start (T27; PLAN §5), for the console's Results page: the funnel of
live Offers, orders per Customer in and out of the Holdout, spend on Sure Things, and Validation by day. Tester
copies are left out of every number. Reads Ground Truth's Response Class, so it belongs to the simulator side.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime

from offer_engine import clock
from offer_engine.customers import population_filter
from offer_engine.domain import Chooser, OfferSource
from offer_engine.rules import in_holdout


@dataclass(frozen=True)
class Funnel:
    sent: int
    claimed: int
    redeemed: int
    spend: float  # ₹ the Redemptions cost
    sure_thing_spend: float  # ₹ of that spend on Sure Things (Ground Truth)


@dataclass(frozen=True)
class GroupOrders:
    customers: int
    orders: int

    @property
    def per_customer(self) -> float | None:
        return self.orders / self.customers if self.customers else None


@dataclass(frozen=True)
class HoldoutComparison:
    treated: GroupOrders  # every population Customer outside the Holdout, offered or not
    holdout: GroupOrders


@dataclass(frozen=True)
class ValidationDay:
    day: date
    decisions: int
    rejections: int  # Decisions with a Validation failure
    fallbacks: int


def funnel(conn: sqlite3.Connection, since: datetime = clock.START) -> Funnel:
    """Live Offers created since `since`: how many went out, were Claimed and were Redeemed, and what they cost."""
    row = conn.execute(
        "SELECT COUNT(o.sent_at),"
        " SUM(EXISTS (SELECT 1 FROM events e WHERE e.offer_id = o.id AND e.kind = 'offer_claimed')),"
        " SUM(o.status = 'redeemed'), SUM(r.amount), SUM(CASE WHEN rc.response_class = 'sure_thing'"
        " THEN r.amount END)"
        " FROM offers o JOIN customers c ON c.id = o.customer_id"
        " LEFT JOIN events r ON r.offer_id = o.id AND r.kind = 'offer_redeemed'"
        " LEFT JOIN sim_response_class rc ON rc.customer_id = o.customer_id"
        f" WHERE o.source = ? AND o.created_at >= ? AND {population_filter('c')}",
        (OfferSource.LIVE, _iso(since)),
    ).fetchone()
    return Funnel(row[0], row[1] or 0, row[2] or 0, row[3] or 0.0, row[4] or 0.0)


def holdout_comparison(
    conn: sqlite3.Connection, holdout_pct: float, since: datetime = clock.START
) -> HoldoutComparison:
    """Orders since `since` by population Customers outside and inside the Holdout at `holdout_pct`."""
    orders = Counter(
        dict(
            conn.execute(
                "SELECT customer_id, COUNT(*) FROM events WHERE kind = 'order' AND at >= ? GROUP BY 1",
                (_iso(since),),
            )
        )
    )
    groups = {True: [0, 0], False: [0, 0]}
    for (customer_id,) in conn.execute(f"SELECT id FROM customers WHERE {population_filter()}"):
        group = groups[in_holdout(customer_id, holdout_pct)]
        group[0] += 1
        group[1] += orders[customer_id]
    return HoldoutComparison(GroupOrders(*groups[False]), GroupOrders(*groups[True]))


def validation_by_day(conn: sqlite3.Connection, since: datetime = clock.START) -> list[ValidationDay]:
    """Decisions per simulated day since `since`, with how many failed Validation and how many were Fallbacks."""
    rows = conn.execute(
        "SELECT substr(d.at, 1, 10), COUNT(*), SUM(d.validation_failures != '[]'), SUM(d.chooser = ?)"
        f" FROM decisions d JOIN customers c ON c.id = d.customer_id WHERE d.at >= ? AND {population_filter('c')}"
        " GROUP BY 1 ORDER BY 1",
        (Chooser.FALLBACK, _iso(since)),
    )
    return [
        ValidationDay(date.fromisoformat(day), n, rejected, fallbacks) for day, n, rejected, fallbacks in rows
    ]


def failure_codes(conn: sqlite3.Connection, since: datetime = clock.START) -> list[tuple[str, int]]:
    """Validation failure codes (the text before `:`) since `since`, most frequent first."""
    counts: Counter[str] = Counter()
    for (failures,) in conn.execute(
        "SELECT d.validation_failures FROM decisions d JOIN customers c ON c.id = d.customer_id"
        f" WHERE d.at >= ? AND d.validation_failures != '[]' AND {population_filter('c')}",
        (_iso(since),),
    ):
        counts.update(failure.split(":", 1)[0] for failure in json.loads(failures))
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="seconds")
