from collections import Counter

import pytest
from hypothesis import given
from hypothesis import strategies as st

from offer_engine.cli import main
from offer_engine.db import connect
from offer_engine.domain import Category, OfferType
from offer_engine.sim.generate import run
from offer_engine.sim.ground_truth import (
    PERSUADABLE_LIFT,
    SURE_THING_BASE,
    TARGET_SHARES,
    TYPICAL_PCT,
    GroundTruth,
    load,
    load_all,
    offer_depth,
    p_buy,
    response_class,
)

N_CUSTOMERS = 2_000
FASHION = Category("fashion", 45.0, 1400.0)

depths = st.floats(0, 5, allow_nan=False)
bases = st.floats(0, 1, allow_nan=False)
ks = st.floats(0.01, 3, allow_nan=False)


def gt(base=0.02, max_lift=0.1, k=0.12, offer_type=OfferType.PCT_CATEGORY):
    return GroundTruth("C00001", offer_type, base, max_lift, k)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    path = tmp_path_factory.mktemp("gt") / "world.db"
    conn = connect(path)
    run(conn, N_CUSTOMERS, months=12, seed=7)
    yield conn, path
    conn.close()


@given(bases, st.floats(0.001, 1), ks, depths, depths)
def test_p_buy_rises_with_depth_for_positive_lift(base, max_lift, k, d1, d2):
    lo, hi = sorted((d1, d2))
    assert p_buy(gt(base, max_lift, k), lo) <= p_buy(gt(base, max_lift, k), hi)


@given(bases, st.floats(-1, -0.001), ks, depths, depths)
def test_p_buy_falls_with_depth_for_negative_lift(base, max_lift, k, d1, d2):
    lo, hi = sorted((d1, d2))
    assert p_buy(gt(base, max_lift, k), lo) >= p_buy(gt(base, max_lift, k), hi)


@given(bases, st.floats(-2, 2, allow_nan=False), ks, depths)
def test_p_buy_stays_a_probability(base, max_lift, k, depth):
    assert 0 <= p_buy(gt(base, max_lift, k), depth) <= 1


def test_p_buy_formula():
    assert p_buy(gt(0.02, 0.1, 0.12), 0) == 0.02
    assert p_buy(gt(0.02, 0.1, 0.12), 0.12) == pytest.approx(0.02 + 0.1 * (1 - 1 / 2.718281828))


@pytest.mark.parametrize(
    ("offer_type", "params", "category", "depth"),
    [
        (OfferType.PCT_CATEGORY, {"pct": 15, "cap": 200}, FASHION, 0.15),
        (OfferType.FLAT_ABOVE_MIN, {"amount": 140, "min_basket": 1000}, FASHION, 0.1),
        (OfferType.FREE_SHIPPING, {}, None, 1.0),
        (OfferType.NUDGE, {}, None, 1.0),
        (OfferType.POINTS_MULTIPLIER, {"multiplier": 2.5}, None, 1.5),
    ],
)
def test_offer_depth(offer_type, params, category, depth):
    assert offer_depth(offer_type, params, category) == pytest.approx(depth)


def test_flat_depth_needs_a_category():
    with pytest.raises(ValueError, match="category"):
        offer_depth(OfferType.FLAT_ABOVE_MIN, {"amount": 100}, None)


def max_lift_for(lift, k=0.12):
    """The max Lift whose typical-Offer Lift is `lift`."""
    return lift / (1 - 2.718281828 ** (-TYPICAL_PCT / 100 / k))


@pytest.mark.parametrize(
    ("base", "lift", "expected"),
    [
        (0.3, -0.001, "sleeping_dog"),
        (0.001, -0.0005, "sleeping_dog"),
        (SURE_THING_BASE, 0.0, "sure_thing"),
        (SURE_THING_BASE, PERSUADABLE_LIFT * 2, "sure_thing"),
        (SURE_THING_BASE - 0.001, PERSUADABLE_LIFT * 1.01, "persuadable"),
        (SURE_THING_BASE - 0.001, PERSUADABLE_LIFT * 0.99, "lost_cause"),
        (0.0, 0.0, "lost_cause"),
    ],
)
def test_response_class_thresholds(base, lift, expected):
    others = [gt(base, 0.5, 0.5, t) for t in OfferType if t != OfferType.PCT_CATEGORY]
    assert response_class([*others, gt(base, max_lift_for(lift))]) == expected


def test_every_customer_and_offer_type_has_ground_truth(world):
    conn, _ = world
    everyone = load_all(conn)
    assert len(everyone) == N_CUSTOMERS
    assert all(set(gts) == set(OfferType) for gts in everyone.values())
    assert load(conn, "C00042") == everyone["C00042"]
    classes = dict(conn.execute("SELECT customer_id, response_class FROM sim_response_class").fetchall())
    assert classes == {cid: response_class(list(gts.values())) for cid, gts in everyone.items()}


def test_class_shares_hit_calibration_target_9(world):
    conn, _ = world
    counts = Counter(row[0] for row in conn.execute("SELECT response_class FROM sim_response_class"))
    for name, (lo, hi) in TARGET_SHARES.items():
        assert lo <= counts[name] / N_CUSTOMERS <= hi, name


def test_base_tracks_observed_buying(world):
    """Customers with more orders in the last 8 weeks have a higher base."""
    conn, _ = world
    recent = dict(
        conn.execute(
            "SELECT customer_id, COUNT(*) FROM events WHERE kind = 'order' AND at >= '2026-10-06' GROUP BY 1"
        ).fetchall()
    )
    bases = {cid: gts[OfferType.NUDGE].base for cid, gts in load_all(conn).items()}
    buyers = [bases[c] for c in bases if recent.get(c, 0) >= 2]
    others = [bases[c] for c in bases if c not in recent]
    assert sum(buyers) / len(buyers) > 5 * sum(others) / len(others)


def test_coupon_heavy_customers_respond_more_to_discounts(world):
    """Customers who burned points on at least half their orders (observable) have higher discount max Lift."""
    conn, _ = world
    query = (
        "SELECT o.customer_id, COUNT(*), SUM(EXISTS(SELECT 1 FROM events b WHERE b.kind = 'points_burned'"
        " AND b.customer_id = o.customer_id AND b.at = o.at)) FROM events o WHERE o.kind = 'order'"
        " GROUP BY 1 HAVING COUNT(*) >= 2"
    )
    everyone = load_all(conn)
    heavy, other = [], []
    for cid, orders, burned in conn.execute(query):
        lifts = [everyone[cid][t].max_lift for t in (OfferType.PCT_CATEGORY, OfferType.FLAT_ABOVE_MIN)]
        (heavy if burned / orders >= 0.5 else other).extend(lifts)
    assert len(heavy) > 50 and len(other) > 50
    assert sum(heavy) / len(heavy) > 2 * sum(other) / len(other)


def test_nudge_lift_is_positive_except_for_sleeping_dogs(world):
    conn, _ = world
    query = (
        "SELECT r.response_class, g.max_lift FROM sim_ground_truth g JOIN sim_response_class r"
        " USING (customer_id) WHERE g.offer_type = 'nudge'"
    )
    for cls, max_lift in conn.execute(query):
        assert (max_lift < 0) == (cls == "sleeping_dog")


def test_summary_command(world, monkeypatch, capsys):
    _, path = world
    monkeypatch.setenv("DB_PATH", str(path))
    assert main(["ground-truth", "summary"]) == 0
    out = capsys.readouterr().out
    assert "OUTSIDE" not in out and out.count(" ok") == 4
    assert all(str(t) in out for t in OfferType)


def test_summary_without_ground_truth(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "empty.db"))
    with pytest.raises(SystemExit, match="generate"):
        main(["ground-truth", "summary"])
