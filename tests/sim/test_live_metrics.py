"""Live metrics for the Results page (T27) on a hand-built database."""

import json
from datetime import date, datetime

import pytest

from offer_engine.rules import in_holdout
from offer_engine.sim.live_metrics import Funnel, failure_codes, funnel, holdout_comparison, validation_by_day

IDS = [f"C{i:05d}" for i in range(1, 41)]
HOLDOUT = [c for c in IDS if in_holdout(c, 10.0)]
TREATED = [c for c in IDS if not in_holdout(c, 10.0)]


def add_customer(conn, cid, response_class="persuadable", tester_copy=False):
    conn.execute(
        "INSERT INTO customers (id, signup_at, city_tier, device, channel, loyalty_tier, is_tester_copy)"
        " VALUES (?, '2026-01-01T00:00:00', 1, 'android', 'organic', 'silver', ?)",
        (cid, int(tester_copy)),
    )
    conn.execute("INSERT INTO sim_response_class VALUES (?, ?)", (cid, response_class))


def add_offer(conn, cid, *, sent=True, claimed=False, cost=None, source="live", at="2026-12-01T10:00:00"):
    """A live Offer, Claimed and/or Redeemed (when `cost` is given) through events. Returns its id."""
    status = "redeemed" if cost is not None else "claimed" if claimed else "sent" if sent else "queued"
    offer_id = conn.execute(
        "INSERT INTO offers (code, customer_id, offer_type, category, created_at, send_at, expires_at, rule_version,"
        " worst_case_cost, expected_cost, status, source, sent_at)"
        " VALUES (?, ?, 'pct_category', 'fashion', ?, ?, '2026-12-04T10:00:00', 0, 300, 60, ?, ?, ?)",
        (
            f"POE-{conn.execute('SELECT COUNT(*) FROM offers').fetchone()[0]:06d}",
            cid,
            at,
            at,
            status,
            source,
            at if sent else None,
        ),
    ).lastrowid
    if claimed or cost is not None:
        add_event(conn, cid, "offer_claimed", offer_id=offer_id)
    if cost is not None:
        add_event(conn, cid, "order", amount=1000.0, offer_id=offer_id)
        add_event(conn, cid, "offer_redeemed", amount=cost, offer_id=offer_id)
    return offer_id


def add_event(conn, cid, kind, at="2026-12-02T12:00:00", amount=None, offer_id=None):
    conn.execute(
        "INSERT INTO events (customer_id, at, kind, amount, offer_id) VALUES (?, ?, ?, ?, ?)",
        (cid, at, kind, amount, offer_id),
    )


def add_decision(conn, cid, at, chooser="rules", failures=()):
    conn.execute(
        "INSERT INTO decisions (customer_id, at, trigger, chooser, rule_version, validation_failures)"
        " VALUES (?, ?, 'daily_sweep', ?, 0, ?)",
        (cid, at, chooser, json.dumps(list(failures))),
    )


@pytest.fixture
def db(conn):
    for cid in IDS:
        add_customer(conn, cid)
    add_customer(conn, "C00001-t42", tester_copy=True)
    conn.execute(
        "UPDATE sim_response_class SET response_class = 'sure_thing' WHERE customer_id = ?", (TREATED[1],)
    )
    return conn


def test_holdout_split_is_not_degenerate():
    assert HOLDOUT and len(TREATED) > 3


def test_funnel_counts_sent_claimed_redeemed_and_spend(db):
    add_offer(db, TREATED[0], sent=False)
    add_offer(db, TREATED[0])
    add_offer(db, TREATED[0], claimed=True)
    add_offer(db, TREATED[1], cost=120.0)  # a Sure Thing
    add_offer(db, TREATED[2], cost=80.0)
    add_offer(db, "C00001-t42", cost=500.0)  # Tester copy: left out
    add_offer(db, TREATED[3], cost=999.0, source="history_random", at="2026-11-20T10:00:00")

    f = funnel(db)
    assert (f.sent, f.claimed, f.redeemed) == (4, 3, 2)
    assert f.spend == 200.0 and f.sure_thing_spend == 120.0


def test_funnel_on_an_empty_world(db):
    assert funnel(db) == Funnel(0, 0, 0, 0.0, 0.0)


def test_holdout_comparison_counts_orders_per_customer_since_the_clock_start(db):
    add_event(db, TREATED[0], "order")
    add_event(db, TREATED[0], "order")
    add_event(db, TREATED[1], "order")
    add_event(db, TREATED[2], "order", at="2026-11-30T23:00:00")  # history: before the clock start
    add_event(db, HOLDOUT[0], "order")
    add_event(db, "C00001-t42", "order")  # Tester copy: left out
    add_event(db, TREATED[3], "session")

    c = holdout_comparison(db, 10.0)
    assert (c.treated.customers, c.treated.orders) == (len(TREATED), 3)
    assert (c.holdout.customers, c.holdout.orders) == (len(HOLDOUT), 1)
    assert c.treated.per_customer == pytest.approx(3 / len(TREATED))
    assert c.holdout.per_customer == pytest.approx(1 / len(HOLDOUT))


def test_no_holdout_has_no_rate(db):
    c = holdout_comparison(db, 0.0)
    assert c.holdout.customers == 0 and c.holdout.per_customer is None
    assert c.treated.customers == len(IDS)


def test_validation_by_day_and_failure_codes(db):
    add_decision(db, "C00002", "2026-12-01T10:00:00")
    add_decision(
        db, "C00003", "2026-12-01T11:00:00", "fallback", ["over_budget: ₹300 > ₹100 left (weekly_budget)"]
    )
    add_decision(
        db,
        "C00004",
        "2026-12-02T10:00:00",
        "fallback",
        ["param_out_of_range: pct=40 > 15 (max_pct_by_loyalty_tier)", "caption_missing: empty caption"],
    )
    add_decision(
        db, "C00005", "2026-12-02T10:00:00", "agent", ["over_budget: ₹90 > ₹10 left (weekly_budget)"]
    )
    add_decision(db, "C00001-t42", "2026-12-02T10:00:00", "fallback", ["over_budget: x"])  # Tester copy
    # Before the clock start.
    add_decision(db, "C00006", "2026-11-30T10:00:00", "fallback", ["over_budget: x"])

    days = validation_by_day(db)
    assert [(d.day, d.decisions, d.rejections, d.fallbacks) for d in days] == [
        (date(2026, 12, 1), 2, 1, 1),
        (date(2026, 12, 2), 2, 2, 1),
    ]
    assert failure_codes(db) == [("over_budget", 2), ("caption_missing", 1), ("param_out_of_range", 1)]
    assert failure_codes(db, since=datetime(2026, 12, 2)) == [
        ("caption_missing", 1),
        ("over_budget", 1),
        ("param_out_of_range", 1),
    ]
