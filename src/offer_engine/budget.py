"""The weekly budget at `now` (PLAN §3.3): what live Offers have spent this week and what outstanding ones reserve."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from offer_engine.domain import BudgetMode, BudgetState, OfferSource, OfferStatus, OfferType, RuleSet
from offer_engine.rules import POINTS_PER_RUPEE

OUTSTANDING = (OfferStatus.QUEUED, OfferStatus.SENT, OfferStatus.CLAIMED)


def week_start(now: datetime) -> datetime:
    """Monday 00:00 simulated."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(days=now.weekday())


def budget_state(conn: sqlite3.Connection, rules: RuleSet, now: datetime) -> BudgetState:
    """`reserved`: unexpired outstanding Offers at worst-case or expected cost, per `budget_mode`, whenever they
    were created. `spent`: Offers redeemed this week at their actual cost. Only live Offers count.
    """
    start = week_start(now)
    at_now = now.isoformat(timespec="seconds")
    column = "worst_case_cost" if rules.budget_mode == BudgetMode.WORST_CASE else "expected_cost"
    marks = ",".join("?" * len(OUTSTANDING))
    reserved = conn.execute(
        f"SELECT COALESCE(SUM({column}), 0) FROM offers "
        f"WHERE source = ? AND status IN ({marks}) AND expires_at > ? AND created_at <= ?",
        (OfferSource.LIVE, *OUTSTANDING, at_now, at_now),
    ).fetchone()[0]

    spent = 0.0
    query = (
        "SELECT o.offer_type, o.params, o.worst_case_cost, "
        "(SELECT amount FROM events e WHERE e.offer_id = o.id AND e.kind = 'order' LIMIT 1) AS basket "
        "FROM offers o WHERE o.source = ? AND o.status = ? AND o.redeemed_at >= ? AND o.redeemed_at <= ?"
    )
    params = (OfferSource.LIVE, OfferStatus.REDEEMED, start.isoformat(timespec="seconds"), at_now)
    for row in conn.execute(query, params):
        if row["basket"] is None:
            spent += row["worst_case_cost"]
        else:
            spent += redemption_cost(
                OfferType(row["offer_type"]), json.loads(row["params"]), row["basket"], rules
            )
    return BudgetState(week_start=start, spent=spent, reserved=float(reserved))


def redemption_cost(offer_type: OfferType, params: dict[str, float], basket: float, rules: RuleSet) -> float:
    """What a Redemption on an order of `basket` ₹ actually cost."""
    if offer_type == OfferType.PCT_CATEGORY:
        return min(params["pct"] * basket / 100, params["cap"])
    if offer_type == OfferType.FLAT_ABOVE_MIN:
        return params["amount"]
    if offer_type == OfferType.FREE_SHIPPING:
        return rules.shipping_fee
    if offer_type == OfferType.POINTS_MULTIPLIER:
        return (params["multiplier"] - 1) * basket * POINTS_PER_RUPEE * rules.point_value
    return 0.0
