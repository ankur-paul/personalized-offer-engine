"""Weekly budget (T09, PLAN §3.3): spent this week and Reserved Budget at worst-case or expected cost."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from offer_engine.budget import budget_state, redemption_cost, week_start
from offer_engine.domain import BudgetMode, OfferType, RuleSet

MONDAY = datetime(2026, 12, 7)
NOW = MONDAY + timedelta(days=2, hours=10)  # Wednesday 10:00


@pytest.fixture
def db(conn):
    conn.execute(
        "INSERT INTO customers (id, signup_at, city_tier, device, channel, loyalty_tier)"
        " VALUES ('C1', '2026-01-01T00:00:00', 1, 'android', 'organic', 'silver')"
    )
    conn.commit()
    return conn


def add_offer(
    conn,
    status="queued",
    *,
    worst=100.0,
    expected=20.0,
    created=NOW - timedelta(hours=1),
    expires=NOW + timedelta(days=2),
    redeemed=None,
    source="live",
    offer_type="flat_above_min",
    params=None,
    basket=None,
) -> int:
    n = conn.execute("SELECT COUNT(*) FROM offers").fetchone()[0]
    cur = conn.execute(
        "INSERT INTO offers (code, customer_id, offer_type, params, created_at, send_at, expires_at, rule_version,"
        " worst_case_cost, expected_cost, status, source, redeemed_at) VALUES (?, 'C1', ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)",
        (
            f"POE-{n:06d}",
            offer_type,
            json.dumps(params or {"amount": worst, "min_basket": 1000.0}),
            created.isoformat(),
            created.isoformat(),
            expires.isoformat(),
            worst,
            expected,
            status,
            source,
            redeemed.isoformat() if redeemed else None,
        ),
    )
    if basket is not None:
        conn.execute(
            "INSERT INTO events (customer_id, at, kind, amount, offer_id) VALUES ('C1', ?, 'order', ?, ?)",
            (redeemed.isoformat(), basket, cur.lastrowid),
        )
    conn.commit()
    return cur.lastrowid


def test_week_starts_monday_midnight():
    assert week_start(NOW) == MONDAY
    assert week_start(MONDAY) == MONDAY
    assert week_start(MONDAY - timedelta(seconds=1)) == MONDAY - timedelta(days=7)


def test_reserved_at_worst_case_or_expected_cost(db):
    for status in ("queued", "sent", "claimed"):
        add_offer(db, status, worst=100.0, expected=20.0)
    assert budget_state(db, RuleSet(), NOW).reserved == pytest.approx(300.0)
    assert budget_state(db, RuleSet(budget_mode=BudgetMode.EXPECTED), NOW).reserved == pytest.approx(60.0)


def test_reserved_counts_outstanding_offers_from_earlier_weeks(db):
    add_offer(db, "sent", created=MONDAY - timedelta(days=1), expires=NOW + timedelta(hours=1))
    assert budget_state(db, RuleSet(), NOW).reserved == pytest.approx(100.0)


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "dismissed"},
        {"status": "expired"},
        {"status": "withdrawn"},
        {"status": "sent", "expires": NOW},  # expiry not yet marked
        {"status": "sent", "source": "history_random"},
        {"status": "queued", "created": NOW + timedelta(hours=1)},  # not yet created at `now`
    ],
)
def test_not_reserved(db, fields):
    add_offer(db, fields.pop("status"), **fields)
    assert budget_state(db, RuleSet(), NOW).reserved == 0.0


def test_spent_is_actual_cost_of_this_weeks_redemptions(db):
    pct = {"pct": 10.0, "cap": 150.0}
    add_offer(
        db,
        "redeemed",
        offer_type="pct_category",
        params=pct,
        worst=150.0,
        redeemed=NOW - timedelta(days=1),
        basket=1200.0,
    )  # 10% of 1,200 = 120
    add_offer(
        db, "redeemed", offer_type="pct_category", params=pct, worst=150.0, redeemed=MONDAY, basket=3000.0
    )
    add_offer(db, "redeemed", worst=80.0, redeemed=MONDAY + timedelta(hours=1))  # no order event: worst case
    budget = budget_state(db, RuleSet(), NOW)
    assert budget.spent == pytest.approx(120.0 + 150.0 + 80.0)
    assert budget.reserved == 0.0
    assert budget.week_start == MONDAY


def test_spent_resets_at_the_week_boundary(db):
    add_offer(db, "redeemed", worst=80.0, redeemed=MONDAY - timedelta(seconds=1))
    assert budget_state(db, RuleSet(), NOW).spent == 0.0
    assert budget_state(db, RuleSet(), MONDAY - timedelta(seconds=1)).spent == pytest.approx(80.0)


def test_redemption_cost_per_offer_type():
    rules = RuleSet()
    assert redemption_cost(OfferType.PCT_CATEGORY, {"pct": 10, "cap": 50}, 1000, rules) == 50
    assert redemption_cost(OfferType.FLAT_ABOVE_MIN, {"amount": 75, "min_basket": 900}, 1000, rules) == 75
    assert redemption_cost(OfferType.FREE_SHIPPING, {}, 1000, rules) == rules.shipping_fee
    assert redemption_cost(OfferType.POINTS_MULTIPLIER, {"multiplier": 3}, 1000, rules) == pytest.approx(50.0)
    assert redemption_cost(OfferType.NUDGE, {}, 1000, rules) == 0.0


def test_spent_finds_each_redemptions_order_by_index(db):
    """Every Decision computes the budget, so the order lookup must not scan all events."""
    plan = db.execute(
        "EXPLAIN QUERY PLAN SELECT amount FROM events e WHERE e.offer_id = 1 AND e.kind = 'order' LIMIT 1"
    ).fetchall()
    assert any("events_offer" in row["detail"] for row in plan)
