"""Pick the showcase Customers, one per case (PLAN §4.2, QnA Q9).

This step may read Ground Truth (the `sure_thing` and `persuadable` cases need the Response Class), so it passes
only the Customer ID onward; the card writer never learns why a Customer was picked (ADR 0002).

Every pick is deterministic for a database: candidates are ranked by the case's measure, ties broken by ID.
Cases are filled in `CASES` order and a Customer is picked at most once.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from offer_engine import clock
from offer_engine.domain import RuleSet
from offer_engine.personas import CASES, OPTIONAL_CASES
from offer_engine.rules import in_holdout

# at_risk_high_value: top tenth by lifetime spend, last order 45–120 days ago; the highest spender.
HIGH_VALUE_TOP_SHARE = 0.10
AT_RISK_GAP_DAYS = (45, 120)
# new_one_order: signed up 7–60 days ago and ordered exactly once; the newest.
NEW_SIGNUP_DAYS = (7, 60)
# deal_hunter: at least 2 Redemptions; the most, then the highest Redemption rate.
DEAL_HUNTER_MIN_REDEMPTIONS = 2
# expiring_points: points expire within 14 days; the biggest balance.
EXPIRING_WITHIN_DAYS = 14
# cart_abandoner: 2–8 abandoned carts in the last 30 days; the most, then the latest.
CART_WINDOW_DAYS = 30
CART_ABANDONS = (2, 8)
# sure_thing and holdout: a regular, 3–12 orders in the last 90 days; the most. The bands keep extreme outliers
# (hundreds of orders) out of the showcase.
ACTIVE_DAYS = 90
REGULAR_ORDERS = (3, 12)
# persuadable: 1–12 orders in the last 90 days; the highest mean max Lift across Offer Types.
# Cases meant to show an Offer working skip Customers an Offer can't help.
OFFER_CASES = ("at_risk_high_value", "new_one_order", "deal_hunter", "expiring_points", "cart_abandoner")
NO_HELP_CLASSES = ("sure_thing", "sleeping_dog")


@dataclass(frozen=True)
class ShowcasePick:
    case: str
    customer_id: str


@dataclass
class _Stats:
    signup_at: datetime
    points: int
    points_expire_at: datetime | None
    in_holdout: bool
    response_class: str | None
    mean_max_lift: float = 0.0
    orders: int = 0
    spend: float = 0.0
    last_order_at: datetime | None = None
    recent_orders: int = 0
    recent_abandons: int = 0
    last_abandon_at: datetime | None = None
    redeemed: int = 0
    offers: int = 0


def select_showcase(
    conn: sqlite3.Connection, rules: RuleSet, now: datetime | None = None
) -> list[ShowcasePick]:
    """One pick per case in CASES order. Raises ValueError when a required case has no candidate."""
    now = now or clock.now(conn)
    stats = _load(conn, rules, now)
    picked: set[str] = set()
    picks = []
    for case in CASES:
        candidates = [(cid, s) for cid, s in stats.items() if cid not in picked and _allowed(case, s)]
        best = _best(case, candidates, stats, now)
        if best is None:
            if case in OPTIONAL_CASES:
                continue
            raise ValueError(f"no Customer fits the showcase case {case}; generate a bigger world")
        picked.add(best)
        picks.append(ShowcasePick(case, best))
    return picks


def _allowed(case: str, s: _Stats) -> bool:
    if case == "holdout":
        return s.in_holdout
    if s.in_holdout:
        return False
    if case in OFFER_CASES:
        return s.response_class not in NO_HELP_CLASSES
    return True


def _best(
    case: str, candidates: list[tuple[str, _Stats]], stats: dict[str, _Stats], now: datetime
) -> str | None:
    """The top candidate by the case's ranking key (bigger is better), ties broken by the smaller ID."""
    match case:
        case "at_risk_high_value":
            spenders = sorted((s.spend for s in stats.values() if s.spend > 0), reverse=True)
            if not spenders:
                return None
            threshold = spenders[max(0, int(len(spenders) * HIGH_VALUE_TOP_SHARE) - 1)]
            lo, hi = AT_RISK_GAP_DAYS
            pool = [
                (cid, (s.spend,))
                for cid, s in candidates
                if s.spend >= threshold
                and s.last_order_at
                and now - timedelta(days=hi) <= s.last_order_at <= now - timedelta(days=lo)
            ]
        case "new_one_order":
            pool = [
                (cid, (s.signup_at,))
                for cid, s in candidates
                if s.orders == 1
                and now - timedelta(days=NEW_SIGNUP_DAYS[1])
                <= s.signup_at
                <= now - timedelta(days=NEW_SIGNUP_DAYS[0])
            ]
        case "deal_hunter":
            pool = [
                (cid, (s.redeemed, s.redeemed / s.offers))
                for cid, s in candidates
                if s.redeemed >= DEAL_HUNTER_MIN_REDEMPTIONS
            ]
        case "expiring_points":
            pool = [
                (cid, (s.points,))
                for cid, s in candidates
                if s.points > 0
                and s.points_expire_at
                and now < s.points_expire_at <= now + timedelta(days=EXPIRING_WITHIN_DAYS)
            ]
        case "cart_abandoner":
            pool = [
                (cid, (s.recent_abandons, s.last_abandon_at))
                for cid, s in candidates
                if CART_ABANDONS[0] <= s.recent_abandons <= CART_ABANDONS[1]
            ]
        case "sure_thing":
            pool = [
                (cid, (s.recent_orders,))
                for cid, s in candidates
                if s.response_class == "sure_thing" and _regular(s)
            ]
        case "holdout":
            pool = [(cid, (s.recent_orders,)) for cid, s in candidates if _regular(s)]
        case "persuadable":
            pool = [
                (cid, (s.mean_max_lift,))
                for cid, s in candidates
                if s.response_class == "persuadable" and 1 <= s.recent_orders <= REGULAR_ORDERS[1]
            ]
        case _:
            raise ValueError(f"unknown showcase case {case}")
    if not pool:
        return None
    # `max` keeps the first of equal keys, and the pool is in ID order.
    return max(pool, key=lambda item: item[1])[0]


def _regular(s: _Stats) -> bool:
    return REGULAR_ORDERS[0] <= s.recent_orders <= REGULAR_ORDERS[1]


def _load(conn: sqlite3.Connection, rules: RuleSet, now: datetime) -> dict[str, _Stats]:
    at_now = now.isoformat(timespec="seconds")
    classes = dict(conn.execute("SELECT customer_id, response_class FROM sim_response_class").fetchall())
    lifts = dict(
        conn.execute(
            "SELECT customer_id, AVG(max_lift) FROM sim_ground_truth GROUP BY customer_id"
        ).fetchall()
    )
    stats: dict[str, _Stats] = {}
    for row in conn.execute(
        "SELECT id, signup_at, points_balance, points_expire_at FROM customers"
        " WHERE is_tester_copy = 0 AND opted_out = 0 AND signup_at <= ? ORDER BY id",
        (at_now,),
    ):
        cid = row["id"]
        stats[cid] = _Stats(
            signup_at=datetime.fromisoformat(row["signup_at"]),
            points=row["points_balance"],
            points_expire_at=datetime.fromisoformat(row["points_expire_at"])
            if row["points_expire_at"]
            else None,
            in_holdout=in_holdout(cid, rules.holdout_pct),
            response_class=classes.get(cid),
            mean_max_lift=lifts.get(cid) or 0.0,
        )
    active_since = (now - timedelta(days=ACTIVE_DAYS)).isoformat(timespec="seconds")
    cart_since = (now - timedelta(days=CART_WINDOW_DAYS)).isoformat(timespec="seconds")
    for cid, orders, spend, last, recent in conn.execute(
        "SELECT customer_id, COUNT(*), SUM(amount), MAX(at), SUM(at >= ?) FROM events"
        " WHERE kind = 'order' AND at <= ? GROUP BY customer_id",
        (active_since, at_now),
    ):
        if cid in stats:
            s = stats[cid]
            s.orders, s.spend, s.recent_orders = orders, spend or 0.0, recent
            s.last_order_at = datetime.fromisoformat(last)
    for cid, n, last in conn.execute(
        "SELECT customer_id, COUNT(*), MAX(at) FROM events"
        " WHERE kind = 'cart_abandoned' AND at >= ? AND at <= ? GROUP BY customer_id",
        (cart_since, at_now),
    ):
        if cid in stats:
            stats[cid].recent_abandons, stats[cid].last_abandon_at = n, datetime.fromisoformat(last)
    offers: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for cid, n, redeemed in conn.execute(
        "SELECT customer_id, COUNT(*), SUM(status = 'redeemed') FROM offers WHERE created_at <= ? GROUP BY 1",
        (at_now,),
    ):
        offers[cid] = [n, redeemed]
    for cid, (n, redeemed) in offers.items():
        if cid in stats:
            stats[cid].offers, stats[cid].redeemed = n, redeemed
    return stats
