"""Offer outcomes (T18): Claims, Redemptions and expiry settled by Ground Truth in the live world."""

import json
import shutil
from datetime import datetime, timedelta

import numpy as np
import pytest

from offer_engine import clock, daily_sweep, triggers
from offer_engine.db import connect, load_catalog
from offer_engine.domain import OfferType
from offer_engine.sim.generate import run
from offer_engine.sim.world import day_step, outcomes
from offer_engine.sim.world.day_step import DayReport
from offer_engine.sim.world.offer_economics import redemption_order

START = clock.START
SENT = START + timedelta(hours=10)
EXPIRES = SENT + timedelta(days=3)


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    path = tmp_path_factory.mktemp("outcomes") / "world.db"
    conn = connect(path)
    run(conn, 200, months=3, seed=11)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    return path


@pytest.fixture(autouse=True)
def no_decisions(monkeypatch):
    monkeypatch.setattr(triggers, "on_hour", lambda conn, now, new_events, report: None)
    monkeypatch.setattr(daily_sweep, "on_hour", lambda conn, now, report: None)


@pytest.fixture
def make_world(template, tmp_path):
    opened = []

    def make(name="world"):
        path = tmp_path / f"{name}.db"
        shutil.copy(template, path)
        conn = connect(path)
        opened.append(conn)
        return conn

    yield make
    for conn in opened:
        conn.close()


@pytest.fixture
def world(make_world):
    return make_world()


def customer_ids(conn, n):
    return [row[0] for row in conn.execute("SELECT id FROM customers ORDER BY id LIMIT ?", (n,))]


def add_offer(
    conn,
    customer_id,
    code,
    offer_type="pct_category",
    params=None,
    category="fashion",
    status="sent",
    sent_at=SENT,
    source="live",
):
    params = {"pct": 20.0, "cap": 300.0} if params is None else params
    cursor = conn.execute(
        "INSERT INTO offers (code, customer_id, offer_type, category, params, created_at, send_at, sent_at, "
        "expires_at, rule_version, worst_case_cost, expected_cost, status, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, ?, ?)",
        (
            code,
            customer_id,
            offer_type,
            category,
            json.dumps(params),
            sent_at.isoformat(),
            sent_at.isoformat(),
            sent_at.isoformat(),
            (sent_at + timedelta(days=3)).isoformat(),
            status,
            source,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def hour(conn, now, seed=0):
    report = DayReport(now - timedelta(hours=1), now)
    clock.set_now(conn, now)
    outcomes.on_hour(conn, now, report, np.random.default_rng(seed))
    return report


def status(conn, offer_id):
    return conn.execute("SELECT status FROM offers WHERE id = ?", (offer_id,)).fetchone()[0]


def fate(conn, offer_id):
    return conn.execute("SELECT * FROM sim_offer_fates WHERE offer_id = ?", (offer_id,)).fetchone()


def offer_events(conn, offer_id):
    return conn.execute("SELECT * FROM events WHERE offer_id = ? ORDER BY id", (offer_id,)).fetchall()


def make_buyer(conn, customer_id):
    """Shops so often that Ground Truth's base, and so p_buy, is about 1."""
    conn.execute(
        "UPDATE sim_customer_traits SET visit_rate = 40, buy_propensity = 30, churned_at = NULL "
        "WHERE customer_id = ?",
        (customer_id,),
    )
    conn.commit()


def make_idle(conn, customer_id):
    conn.execute(
        "UPDATE sim_customer_traits SET visit_rate = 0, churned_at = NULL WHERE customer_id = ?",
        (customer_id,),
    )
    conn.commit()


def attach(conn, customer_id, kind, chat_id=99):
    conn.execute(
        "INSERT INTO chats (customer_id, chat_id, kind) VALUES (?, ?, ?)", (customer_id, chat_id, kind)
    )
    conn.commit()


# --- Customers without a chat ------------------------------------------------------------------


def test_redemption_rate_matches_mean_p_buy_over_20000_offers(world):
    rng = np.random.default_rng(1)
    customers = customer_ids(world, 200)
    categories = list(load_catalog(world).categories)
    kinds = [
        ("pct_category", lambda: {"pct": float(rng.integers(5, 31)), "cap": 400.0}),
        ("flat_above_min", lambda: {"amount": float(rng.integers(10, 51) * 10), "min_basket": 1500.0}),
        ("free_shipping", dict),
        ("nudge", dict),
        ("points_multiplier", lambda: {"multiplier": round(float(rng.uniform(1.5, 3)), 1)}),
    ]
    rows = []
    for i in range(20_000):
        offer_type, params = kinds[i % len(kinds)]
        category = categories[int(rng.integers(len(categories)))]
        rows.append(
            (f"POE-{i:06d}", customers[i % len(customers)], offer_type, category, json.dumps(params()))
            + (SENT.isoformat(),) * 3
            + (EXPIRES.isoformat(),)
        )
    world.executemany(
        "INSERT INTO offers (code, customer_id, offer_type, category, params, created_at, send_at, sent_at, "
        "expires_at, rule_version, worst_case_cost, expected_cost, status, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 'sent', 'live')",
        rows,
    )
    world.commit()

    first = hour(world, SENT + timedelta(hours=1))
    report = hour(world, EXPIRES)

    p = world.execute("SELECT AVG(p_used), COUNT(*) FROM sim_offer_fates").fetchone()
    assert p[1] == 20_000
    redeemed = first.counts["redeemed"] + report.counts["redeemed"]
    assert (
        redeemed
        == world.execute(
            "SELECT COUNT(*) FROM offers WHERE status = 'redeemed' AND source = 'live'"
        ).fetchone()[0]
    )
    assert abs(redeemed / 20_000 - p[0]) < 0.01
    assert 0.01 < p[0] < 0.5

    claims = world.execute(
        "SELECT COUNT(DISTINCT offer_id) FROM events e JOIN offers o ON o.id = e.offer_id "
        "WHERE e.kind = 'offer_claimed' AND o.source = 'live'"
    ).fetchone()[0]
    assert claims >= redeemed
    # Every Redeemer claimed, and about 25% of the others (opt-outs aside).
    claimed_only = claims - redeemed
    assert 0.22 < claimed_only / (20_000 - redeemed) < 0.27
    unclaimed_redeemers = world.execute(
        "SELECT COUNT(*) FROM offers o WHERE o.status = 'redeemed' AND o.source = 'live' AND NOT EXISTS "
        "(SELECT 1 FROM events e WHERE e.offer_id = o.id AND e.kind = 'offer_claimed')"
    ).fetchone()[0]
    assert unclaimed_redeemers == 0
    assert (
        report.counts["expired"]
        == world.execute(
            "SELECT COUNT(*) FROM offers WHERE status = 'expired' AND source = 'live'"
        ).fetchone()[0]
    )


def test_a_buyer_claims_then_redeems_inside_the_window(world):
    (customer,) = customer_ids(world, 1)
    make_buyer(world, customer)
    offer_id = add_offer(world, customer, "POE-BUY001")
    hour(world, SENT + timedelta(hours=1))
    f = fate(world, offer_id)
    assert f["buys"] == 1 and f["source"] == "ground_truth" and f["p_used"] > 0.99
    buy_at, claim_at = datetime.fromisoformat(f["buy_at"]), datetime.fromisoformat(f["claim_at"])
    assert SENT <= claim_at <= buy_at < EXPIRES

    report = hour(world, EXPIRES)
    assert status(world, offer_id) == "redeemed"
    assert report.counts["redeemed"] == 1 and report.counts["claimed"] == 1
    events = offer_events(world, offer_id)
    assert [e["kind"] for e in events] == ["offer_claimed", "order", "offer_redeemed"]
    assert events[0]["at"] == claim_at.isoformat() and events[1]["at"] == buy_at.isoformat()
    assert events[1]["category"] == "fashion" and events[1]["amount"] > 0
    assert events[2]["amount"] == pytest.approx(min(0.2 * events[1]["amount"], 300), abs=0.01)
    row = world.execute("SELECT redeemed_at FROM offers WHERE id = ?", (offer_id,)).fetchone()
    assert row[0] == buy_at.isoformat()
    delivery = world.execute(
        "SELECT at, amount FROM sim_pending_events WHERE customer_id = ? AND kind = 'delivered' AND drawn = 0 "
        "AND at = ?",
        (customer, (buy_at + timedelta(days=3)).isoformat()),
    ).fetchone()
    assert delivery is not None and delivery["amount"] == events[1]["amount"]


def test_fates_are_drawn_once_and_times_act_only_when_passed(world):
    (customer,) = customer_ids(world, 1)
    make_buyer(world, customer)
    offer_id = add_offer(world, customer, "POE-ONCE01")
    hour(world, SENT + timedelta(hours=1))
    first = tuple(fate(world, offer_id))
    buy_at = datetime.fromisoformat(first[2])
    if buy_at >= SENT + timedelta(hours=2):
        hour(world, SENT + timedelta(hours=2), seed=5)
        assert tuple(fate(world, offer_id)) == first
        assert status(world, offer_id) in ("sent", "claimed")
        assert not [e for e in offer_events(world, offer_id) if e["kind"] == "order"]


def test_points_multiplier_redemption_schedules_the_bonus_points(world):
    (customer,) = customer_ids(world, 1)
    make_buyer(world, customer)
    offer_id = add_offer(
        world, customer, "POE-PTS001", "points_multiplier", {"multiplier": 3.0}, category=None
    )
    hour(world, SENT + timedelta(hours=1))
    hour(world, EXPIRES)
    order = next(e for e in offer_events(world, offer_id) if e["kind"] == "order")
    bonus = world.execute(
        "SELECT amount FROM sim_pending_events WHERE customer_id = ? AND kind = 'points_earned' AND drawn = 0",
        (customer,),
    ).fetchone()
    assert bonus[0] == int(order["amount"] * 0.1 * 2)


def test_a_non_buyer_expires_unredeemed(world):
    (customer,) = customer_ids(world, 1)
    make_idle(world, customer)
    offer_id = add_offer(world, customer, "POE-IDLE01")
    hour(world, SENT + timedelta(hours=1))
    f = fate(world, offer_id)
    assert f["buys"] == 0 and f["buy_at"] is None and f["p_used"] < 0.05
    report = hour(world, EXPIRES)
    assert status(world, offer_id) in ("expired", "dismissed")
    assert report.counts["redeemed"] == 0


def test_an_opt_out_fate_opts_the_customer_out_and_withdraws_queued_offers(world):
    (customer,) = customer_ids(world, 1)
    offer_id = add_offer(world, customer, "POE-STOP01")
    queued = add_offer(world, customer, "POE-STOP02", status="queued", sent_at=SENT + timedelta(days=1))
    outcomes.save_fate(
        world,
        outcomes.Fate(
            offer_id, False, 0.1, "ground_truth", dismiss_at=SENT + timedelta(hours=5), opts_out=True
        ),
    )
    report = hour(world, SENT + timedelta(hours=6))
    assert report.counts["opted_out"] == 1 and report.counts["dismissed"] == 1
    assert status(world, offer_id) == "dismissed" and status(world, queued) == "withdrawn"
    assert world.execute("SELECT opted_out FROM customers WHERE id = ?", (customer,)).fetchone()[0] == 1
    kinds = [
        r[0]
        for r in world.execute(
            "SELECT kind FROM events WHERE customer_id = ? AND at >= ?", (customer, START.isoformat())
        )
    ]
    assert kinds == ["offer_dismissed", "opted_out"]
    hour(world, EXPIRES + timedelta(days=1))
    assert status(world, offer_id) == "dismissed"


def test_expiry_skips_withdrawn_redeemed_and_past_offers(world):
    customers = customer_ids(world, 4)
    for c in customers:
        make_idle(world, c)
    sent = add_offer(world, customers[0], "POE-EXP001")
    claimed = add_offer(world, customers[1], "POE-EXP002", status="claimed")
    withdrawn = add_offer(world, customers[2], "POE-EXP003", status="withdrawn")
    past = add_offer(world, customers[3], "POE-EXP004", status="claimed", source="history_random")
    hour(world, EXPIRES - timedelta(hours=1))
    assert status(world, claimed) == "claimed"
    report = hour(world, EXPIRES)
    assert status(world, sent) in ("expired", "dismissed")
    assert status(world, claimed) == "expired"
    assert status(world, withdrawn) == "withdrawn"
    assert status(world, past) == "claimed"
    assert report.counts["expired"] >= 1
    assert fate(world, withdrawn) is None and fate(world, past) is None


# --- Testers and Customer Bots -------------------------------------------------------------------


def test_a_tester_claim_draws_the_chance_of_buying_given_a_claim(world):
    (customer,) = customer_ids(world, 1)
    attach(world, customer, "tester")
    offer_id = add_offer(world, customer, "POE-TEST01")
    hour(world, SENT + timedelta(hours=1))
    assert fate(world, offer_id) is None and status(world, offer_id) == "sent"

    world.execute("UPDATE offers SET status = 'claimed' WHERE id = ?", (offer_id,))
    world.commit()
    now = SENT + timedelta(hours=2)
    hour(world, now)
    f = fate(world, offer_id)
    assert f["source"] == "tester_claim" and f["claim_at"] is None
    offer = world.execute(
        f"SELECT {outcomes.OFFER_COLUMNS} FROM offers o LEFT JOIN chats ch ON ch.customer_id = o.customer_id "
        "WHERE o.id = ?",
        (offer_id,),
    ).fetchone()
    p = outcomes.buy_chance(outcomes.sim_customer(world, customer), offer, load_catalog(world), SENT)
    assert f["p_used"] == pytest.approx(p / (p + 0.25 * (1 - p)))
    if f["buys"]:
        assert now <= datetime.fromisoformat(f["buy_at"]) < EXPIRES


def test_a_tester_copy_redeems_on_its_source_and_hears_about_the_order(world):
    (source,) = customer_ids(world, 1)
    make_buyer(world, source)
    copy_id = f"{source}-t42"
    world.execute(
        "INSERT INTO customers (id, signup_at, city_tier, device, channel, loyalty_tier, is_tester_copy, "
        "source_customer_id) SELECT ?, signup_at, city_tier, device, channel, loyalty_tier, 1, id "
        "FROM customers WHERE id = ?",
        (copy_id, source),
    )
    attach(world, copy_id, "tester", chat_id=4242)
    offer_id = add_offer(world, copy_id, "POE-COPY01", status="claimed")
    hour(world, SENT + timedelta(hours=1))
    f = fate(world, offer_id)
    assert f["buys"] == 1 and f["p_used"] > 0.99
    report = hour(world, EXPIRES)
    assert status(world, offer_id) == "redeemed" and report.counts["redeemed"] == 1
    assert report.counts["claimed"] == 0  # the Tester claimed it themselves
    order = next(e for e in offer_events(world, offer_id) if e["kind"] == "order")
    saved = next(e for e in offer_events(world, offer_id) if e["kind"] == "offer_redeemed")["amount"]
    message = world.execute("SELECT chat_id, text, created_at FROM outbox").fetchall()
    assert [tuple(m) for m in message] == [
        (
            4242,
            f"Simulated order: ₹{order['amount']:,.0f} basket, code POE-COPY01 used. You saved ₹{saved:,.0f}.",
            f["buy_at"],
        )
    ]
    # A copy has no organic life, so nothing is delivered to it.
    assert not world.execute("SELECT 1 FROM sim_pending_events WHERE customer_id = ?", (copy_id,)).fetchall()


def test_customer_bot_offers_wait_for_a_roleplay_fate(world):
    (customer,) = customer_ids(world, 1)
    attach(world, customer, "bot")
    offer_id = add_offer(world, customer, "POE-BOT001")
    hour(world, SENT + timedelta(hours=1))
    hour(world, SENT + timedelta(hours=2), seed=3)
    world.execute("UPDATE offers SET status = 'claimed' WHERE id = ?", (offer_id,))
    hour(world, SENT + timedelta(hours=3), seed=4)
    assert fate(world, offer_id) is None and status(world, offer_id) == "claimed"
    assert not [e for e in offer_events(world, offer_id) if e["kind"] == "order"]

    buy_at = SENT + timedelta(hours=20)
    outcomes.save_fate(world, outcomes.Fate(offer_id, True, 0.4, "bot_roleplay", buy_at=buy_at))
    hour(world, SENT + timedelta(hours=21))
    assert status(world, offer_id) == "redeemed"
    assert not world.execute("SELECT * FROM outbox").fetchall()


# --- Organic orders the Offer replaces (docs/QnA.md Q39) ----------------------------------------


def organic_orders(conn, customer_id):
    return [
        datetime.fromisoformat(r[0])
        for r in conn.execute(
            "SELECT at FROM events WHERE customer_id = ? AND kind = 'order' AND offer_id IS NULL AND at >= ?",
            (customer_id, START.isoformat()),
        )
    ]


def test_a_non_buyer_places_no_organic_order_for_7_days_after_the_send(world):
    (customer,) = customer_ids(world, 1)
    make_buyer(world, customer)
    offer_id = add_offer(world, customer, "POE-NOBUY1", status="queued")
    world.execute("UPDATE offers SET sent_at = NULL WHERE id = ?", (offer_id,))
    world.commit()
    outcomes.save_fate(world, outcomes.Fate(offer_id, False, 0.9, "ground_truth"))
    day_step.advance(world, 24 * 9)
    orders = organic_orders(world, customer)
    assert not [at for at in orders if SENT <= at < SENT + timedelta(days=7)]
    assert [at for at in orders if at >= SENT + timedelta(days=7)]
    # The send day's cancelled orders left their carts behind.
    carts = world.execute(
        "SELECT COUNT(*) FROM events WHERE customer_id = ? AND kind = 'cart_abandoned' AND at >= ? AND at < ?",
        (customer, SENT.isoformat(), (SENT + timedelta(days=7)).isoformat()),
    ).fetchone()[0]
    assert carts > 0


def test_a_buyer_orders_organically_again_after_the_redemption(world):
    (customer,) = customer_ids(world, 1)
    make_buyer(world, customer)
    offer_id = add_offer(world, customer, "POE-BUYER2", status="queued")
    world.execute("UPDATE offers SET sent_at = NULL WHERE id = ?", (offer_id,))
    world.commit()
    buy_at = SENT + timedelta(days=1, hours=5)
    outcomes.save_fate(
        world, outcomes.Fate(offer_id, True, 0.9, "ground_truth", buy_at, SENT + timedelta(hours=1))
    )
    day_step.advance(world, 24 * 4)
    assert status(world, offer_id) == "redeemed"
    orders = organic_orders(world, customer)
    assert not [at for at in orders if SENT <= at < buy_at]
    assert [at for at in orders if at >= buy_at]


def test_offers_keep_stopping_mid_day_harmless(make_world):
    whole, split = make_world("whole"), make_world("split")
    for conn in (whole, split):
        for i, customer in enumerate(customer_ids(conn, 30)):
            if i % 2:
                make_buyer(conn, customer)
            add_offer(
                conn,
                customer,
                f"POE-SPLIT{i:02d}",
                status="queued",
                sent_at=START + timedelta(hours=9 + i % 5),
            )
            conn.execute("UPDATE offers SET sent_at = NULL WHERE code = ?", (f"POE-SPLIT{i:02d}",))
        conn.commit()
    day_step.advance(whole, 96)
    for hours in (7, 30, 13, 46):
        day_step.advance(split, hours)
    query = "SELECT customer_id, at, kind, category, product_id, amount, offer_id FROM events WHERE at >= ? ORDER BY id"
    assert [tuple(r) for r in split.execute(query, (START.isoformat(),))] == [
        tuple(r) for r in whole.execute(query, (START.isoformat(),))
    ]
    statuses = "SELECT id, status, redeemed_at FROM offers WHERE source = 'live' ORDER BY id"
    assert [tuple(r) for r in split.execute(statuses)] == [tuple(r) for r in whole.execute(statuses)]
    assert {r[0] for r in whole.execute("SELECT status FROM offers WHERE source = 'live'")} <= {
        "redeemed",
        "expired",
        "dismissed",
    }


def test_the_day_report_counts_outcomes(world):
    customers = customer_ids(world, 20)
    for i, customer in enumerate(customers):
        make_buyer(world, customer)
        add_offer(world, customer, f"POE-REP{i:03d}", status="queued", sent_at=START + timedelta(hours=10))
        world.execute("UPDATE offers SET sent_at = NULL WHERE code = ?", (f"POE-REP{i:03d}",))
    world.commit()
    report = day_step.advance(world, 24 * 4)
    assert report.counts["offers_sent"] == 20
    assert report.counts["redeemed"] == 20 and report.counts["claimed"] == 20
    order_count = world.execute(
        "SELECT COUNT(*) FROM events WHERE kind = 'order' AND at >= ?", (START.isoformat(),)
    ).fetchone()[0]
    assert report.counts["order"] == order_count
    for row in world.execute("SELECT customer_id, sent_at, redeemed_at FROM offers WHERE source = 'live'"):
        sent, redeemed = (datetime.fromisoformat(row[k]) for k in ("sent_at", "redeemed_at"))
        assert not [at for at in organic_orders(world, row["customer_id"]) if sent <= at < redeemed]


# --- Redemption economics ------------------------------------------------------------------------


def test_redemption_order_margin_is_basket_margin_minus_offer_cost(world):
    catalog = load_catalog(world)
    category = catalog.categories["fashion"]
    product = next(p for p in catalog.products.values() if p.category == "fashion")
    rng = np.random.default_rng(3)
    for offer_type, params in [
        (OfferType.PCT_CATEGORY, {"pct": 20.0, "cap": 150.0}),
        (OfferType.FLAT_ABOVE_MIN, {"amount": 200.0, "min_basket": 5000.0}),
        (OfferType.FREE_SHIPPING, {}),
        (OfferType.NUDGE, {}),
        (OfferType.POINTS_MULTIPLIER, {"multiplier": 2.0}),
    ]:
        order = redemption_order(offer_type, params, category, product, rng, basket_size=1.2)
        assert order.basket >= max(product.price, params.get("min_basket", 0))
        assert order.margin == pytest.approx(order.basket * category.margin_pct / 100 - order.discount)
        if offer_type == OfferType.PCT_CATEGORY:
            assert order.discount == min(0.2 * order.basket, 150.0)
        if offer_type == OfferType.NUDGE:
            assert order.discount == 0


def test_cancel_orders_finds_a_customers_orders_by_index(conn):
    """`trim_orders` runs it per Offer window, thousands of times a day on 10k Customers."""
    plan = conn.execute(
        "EXPLAIN QUERY PLAN SELECT id FROM sim_pending_events WHERE drawn = 1 AND kind = 'order'"
        " AND customer_id = 'C1' AND at >= '' AND at < ''"
    ).fetchall()
    assert any("sim_pending_events_customer_at" in row["detail"] for row in plan)
