"""Random past Offers in the history (T14): who gets them, how Ground Truth settles them, and the history they leave."""

import itertools
import json
import re
from collections import defaultdict
from datetime import date, datetime, timedelta

import pytest

from offer_engine import clock
from offer_engine.budget import redemption_cost
from offer_engine.cli import main
from offer_engine.domain import OfferType, RuleSet
from offer_engine.rules import in_holdout
from offer_engine.sim.generate.history import POINTS_PER_RUPEE
from offer_engine.sim.generate.past_offers import (
    HORIZON,
    SEND_CHANCE,
    _broadcast_slots,
    _long_gaps,
    _send_time,
)
from offer_engine.sim.ground_truth import GroundTruth, p_buy, with_base

RULES = RuleSet()


@pytest.fixture
def conn(world_2k):
    return world_2k[0]


def offers(conn, where="1"):
    return conn.execute(f"SELECT * FROM offers WHERE source = 'history_random' AND {where}").fetchall()


def at(iso):
    return datetime.fromisoformat(iso)


# --- Who gets a past Offer ---------------------------------------------------------------------


def test_no_past_offer_to_a_holdout_customer(conn):
    customers = {r["customer_id"] for r in offers(conn)}
    assert customers
    assert not [c for c in customers if in_holdout(c, RULES.holdout_pct)]


def test_about_30_pct_of_moments_draw_an_offer(conn):
    moments, sent = conn.execute("SELECT COUNT(*), COUNT(offer_id) FROM sim_history_moments").fetchone()
    assert abs(sent / moments - SEND_CHANCE) < 0.01
    assert sent == len(offers(conn))
    triggers = {
        r[0] for r in conn.execute("SELECT DISTINCT trigger FROM sim_history_moments WHERE offer_id IS NULL")
    }
    assert triggers == {"cart_abandoned", "long_gap", "broadcast"}


def test_every_offer_type_is_sent_and_settled_inside_the_history(conn):
    rows = offers(conn)
    assert {r["offer_type"] for r in rows} == set(OfferType)
    assert {r["status"] for r in rows} == {"redeemed", "claimed", "dismissed", "expired"}
    for r in rows:
        send_at = at(r["send_at"])
        assert RULES.send_hour_start <= send_at.hour < RULES.send_hour_end
        assert at(r["created_at"]) <= send_at
        assert at(r["expires_at"]) == send_at + timedelta(days=RULES.offer_validity_days)
        assert send_at + HORIZON <= clock.START
        assert re.fullmatch(r"POE-[A-Z0-9]{6}", r["code"])


def test_depths_fall_in_their_ranges(conn):
    for r in offers(conn):
        params = json.loads(r["params"])
        if r["offer_type"] == OfferType.PCT_CATEGORY:
            assert 5 <= params["pct"] <= 30 and 50 <= params["cap"] <= RULES.per_offer_cost_cap
            assert r["category"]
        elif r["offer_type"] == OfferType.FLAT_ABOVE_MIN:
            assert 100 <= params["amount"] <= 500 and params["min_basket"] > params["amount"]
        elif r["offer_type"] == OfferType.POINTS_MULTIPLIER:
            assert 1.5 <= params["multiplier"] <= 3.0


def test_no_offer_after_opting_out(conn):
    opted = {
        r["customer_id"]: at(r["at"]) for r in conn.execute("SELECT * FROM events WHERE kind = 'opted_out'")
    }
    assert opted
    for cid, when in opted.items():
        assert not offers(conn, f"customer_id = '{cid}' AND created_at > '{when.isoformat()}'")
    flagged = {r[0] for r in conn.execute("SELECT id FROM customers WHERE opted_out = 1")}
    assert flagged == set(opted)


# --- How Ground Truth settles them -------------------------------------------------------------


def test_redemption_rate_per_offer_type_matches_mean_p_buy_of_recipients(conn):
    query = (
        "SELECT o.offer_type, AVG(o.status = 'redeemed'), AVG(m.p_buy), COUNT(*) FROM offers o"
        " JOIN sim_history_moments m ON m.offer_id = o.id GROUP BY 1"
    )
    for offer_type, redeemed, mean_p, n in conn.execute(query):
        assert n > 1000
        assert abs(redeemed - mean_p) <= 0.02, offer_type


def test_claims_at_least_redemptions_and_every_redeemer_claimed(conn):
    claims = defaultdict(list)
    for r in conn.execute("SELECT offer_id, at FROM events WHERE kind = 'offer_claimed'"):
        claims[r[0]].append(at(r[1]))
    by_type = defaultdict(lambda: [0, 0])
    for r in offers(conn):
        by_type[r["offer_type"]][0] += r["id"] in claims
        by_type[r["offer_type"]][1] += r["status"] == "redeemed"
        if r["status"] == "redeemed":
            assert len(claims[r["id"]]) == 1
            assert at(r["send_at"]) <= claims[r["id"]][0] <= at(r["redeemed_at"]) < at(r["expires_at"])
        elif r["status"] == "claimed":
            assert len(claims[r["id"]]) == 1
        else:
            assert r["id"] not in claims
    for claimed, redeemed in by_type.values():
        assert claimed >= redeemed > 0


def test_redemption_orders_carry_the_discount(conn):
    orders = {
        r["offer_id"]: r
        for r in conn.execute("SELECT * FROM events WHERE kind = 'order' AND offer_id IS NOT NULL")
    }
    costs = {
        r["offer_id"]: r["amount"] for r in conn.execute("SELECT * FROM events WHERE kind = 'offer_redeemed'")
    }
    redeemed = offers(conn, "status = 'redeemed'")
    assert set(orders) == set(costs) == {r["id"] for r in redeemed}
    for r in redeemed:
        order, params, offer_type = orders[r["id"]], json.loads(r["params"]), OfferType(r["offer_type"])
        assert order["customer_id"] == r["customer_id"] and order["at"] == r["redeemed_at"]
        assert costs[r["id"]] == pytest.approx(
            redemption_cost(offer_type, params, order["amount"], RULES), abs=0.01
        )
        if offer_type == OfferType.PCT_CATEGORY:
            assert order["category"] == r["category"] and costs[r["id"]] <= params["cap"]
        if offer_type == OfferType.FLAT_ABOVE_MIN:
            assert order["amount"] >= params["min_basket"]


def test_points_offer_multiplies_the_points_earned(conn):
    query = (
        "SELECT o.params, b.amount AS basket, p.amount AS points FROM offers o"
        " JOIN events b ON b.offer_id = o.id AND b.kind = 'order'"
        " JOIN events p ON p.customer_id = o.customer_id AND p.kind = 'points_earned'"
        "  AND p.at = strftime('%Y-%m-%dT%H:%M:%S', b.at, '+3 days')"
        " WHERE o.offer_type = 'points_multiplier' AND o.status = 'redeemed'"
    )
    rows = conn.execute(query).fetchall()
    assert rows
    for r in rows:
        multiplier = json.loads(r["params"])["multiplier"]
        assert r["points"] == int(r["basket"] * POINTS_PER_RUPEE * multiplier)


# --- The history they leave --------------------------------------------------------------------


def test_an_offer_decides_whether_the_customer_buys_in_7_days(conn):
    """No organic order between a send and its Redemption, or in the 7 days after a send that wasn't redeemed."""
    query = (
        "SELECT COUNT(*) FROM offers o JOIN events e ON e.customer_id = o.customer_id AND e.kind = 'order'"
        " AND e.offer_id IS NULL AND e.at >= o.send_at"
        " AND e.at < COALESCE(o.redeemed_at, strftime('%Y-%m-%dT%H:%M:%S', o.send_at, '+7 days'))"
        " WHERE o.source = 'history_random'"
    )
    assert conn.execute(query).fetchone()[0] == 0
    kept = (
        "SELECT COUNT(*) FROM offers o JOIN events e ON e.customer_id = o.customer_id AND e.kind = 'order'"
        " AND e.offer_id IS NULL AND e.at > o.redeemed_at"
        " AND e.at < strftime('%Y-%m-%dT%H:%M:%S', o.send_at, '+7 days')"
    )
    assert conn.execute(kept).fetchone()[0] > 0  # a Redeemer's later orders stay


def test_points_events_replay_to_each_balance(conn):
    """For Customers who joined during the history (no starting points): each expiry takes the whole balance and
    the events sum to the Customer's points. A burn isn't checked against the balance: `simulate_day` credits a
    delivery's points at the start of its day, so an organic burn can spend points stamped later that day (T05)."""
    window_start = conn.execute("SELECT MIN(at) FROM events").fetchone()[0]
    customers = conn.execute("SELECT id, points_balance FROM customers WHERE signup_at >= ?", (window_start,))
    expected = dict(customers.fetchall())
    balance = defaultdict(int)
    query = (
        "SELECT customer_id, kind, amount FROM events WHERE kind LIKE 'points_%'"
        " ORDER BY customer_id, at, kind != 'points_expired', id"
    )
    for cid, kind, amount in conn.execute(query):
        if cid not in expected:
            continue
        if kind == "points_earned":
            balance[cid] += amount
        elif kind == "points_burned":
            assert amount > 0
            balance[cid] -= amount
        else:
            assert amount == balance[cid] > 0
            balance[cid] = 0
    assert {cid: balance[cid] for cid in expected} == expected


def test_summary_command_prints_rates_per_offer_type(world_2k, monkeypatch, capsys):
    monkeypatch.setenv("DB_PATH", str(world_2k[1]))
    assert main(["history", "summary"]) == 0
    out = capsys.readouterr().out
    for offer_type in OfferType:
        assert re.search(rf"{offer_type}\s+[\d,]+\s+[\d.]+%\s+[\d.]+%", out)
    for trigger in ("broadcast", "cart_abandoned", "long_gap"):
        assert trigger in out
    assert "calibration target 4" in out


def test_summary_without_history(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "empty.db"))
    with pytest.raises(SystemExit, match="run `offer-engine generate`"):
        main(["history", "summary"])


# --- Moments and the base at a moment ----------------------------------------------------------


def test_long_gaps_every_45_days_without_an_order():
    signup = datetime(2025, 11, 1, 12)
    end = datetime(2026, 6, 1)
    orders = [datetime(2026, 1, 1, 9), datetime(2026, 1, 20, 9)]
    moments = [m.at for m in _long_gaps(signup, orders, date(2025, 12, 1), end, "fashion")]
    assert moments == [
        datetime(2025, 12, 16, 12),  # signup + 45 days, inside the history
        datetime(2026, 3, 6, 9),  # 45 and 90 days after the last order
        datetime(2026, 4, 20, 9),
    ]


def test_send_time_moves_into_the_send_hours():
    assert _send_time(datetime(2026, 3, 1, 7, 30)) == datetime(2026, 3, 1, 9)
    assert _send_time(datetime(2026, 3, 1, 14, 5)) == datetime(2026, 3, 1, 14, 5)
    assert _send_time(datetime(2026, 3, 1, 22, 15)) == datetime(2026, 3, 2, 9)


def test_broadcasts_are_weekly_on_friday_evening():
    slots = _broadcast_slots(date(2026, 3, 1), date(2026, 3, 22))
    assert slots == [datetime(2026, 3, 6, 18), datetime(2026, 3, 13, 18), datetime(2026, 3, 20, 18)]


def test_with_base_keeps_lift_and_scales_a_sleeping_dogs_drop():
    persuadable = GroundTruth("C1", OfferType.PCT_CATEGORY, 0.02, 0.10, 0.12)
    assert p_buy(with_base(persuadable, 0.05), 0.15) - 0.05 == pytest.approx(p_buy(persuadable, 0.15) - 0.02)
    dog = GroundTruth("C1", OfferType.PCT_CATEGORY, 0.10, -0.05, 0.12)
    assert with_base(dog, 0.20).max_lift == pytest.approx(-0.10)
    assert with_base(GroundTruth("C1", OfferType.NUDGE, 0.0, -0.0, 0.5), 0.1).base == 0.1


def test_one_past_offer_at_a_time(conn):
    """No moment is drawn inside an earlier Offer's 7 days, so no two Offers' spans overlap."""
    sends = defaultdict(list)
    for r in offers(conn):
        sends[r["customer_id"]].append(at(r["send_at"]))
    for times in sends.values():
        times.sort()
        assert all(b - a >= HORIZON for a, b in itertools.pairwise(times))
    query = (
        "SELECT COUNT(*) FROM sim_history_moments m JOIN offers o ON o.customer_id = m.customer_id"
        " AND m.at > o.send_at AND m.at < strftime('%Y-%m-%dT%H:%M:%S', o.send_at, '+7 days')"
    )
    assert conn.execute(query).fetchone()[0] == 0
