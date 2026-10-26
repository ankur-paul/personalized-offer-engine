"""The truth panel's numbers (T40): Ground Truth's chances for one Customer's Decision, on the 50-Customer world."""

import pytest

from offer_engine import clock
from offer_engine.db import load_catalog
from offer_engine.domain import OfferType
from offer_engine.sim import ground_truth
from offer_engine.sim.explain import Candidate, truth_for
from offer_engine.sim.world import outcomes

AT = clock.START
# Response Classes of the seed-7 world.
SLEEPING_DOG, LOST_CAUSE = "C00010", "C00001"
CANDIDATES = (
    Candidate(OfferType.PCT_CATEGORY, "fashion", {"pct": 20.0, "cap": 300.0}),
    Candidate(OfferType.FREE_SHIPPING, None, {}),
    Candidate(OfferType.NUDGE, None, {}),
)


def add_offer(conn, customer_id, offer_type="pct_category", category="fashion", params='{"pct": 10.0}'):
    cursor = conn.execute(
        "INSERT INTO offers (code, customer_id, offer_type, category, params, created_at, send_at, sent_at, "
        "expires_at, rule_version, worst_case_cost, expected_cost, status, source) "
        "VALUES ('POE-TEST01', ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 'sent', 'live')",
        (customer_id, offer_type, category, params, *[AT.isoformat()] * 4),
    )
    return conn.execute("SELECT * FROM offers WHERE id = ?", (cursor.lastrowid,)).fetchone()


def test_the_no_offer_chance_is_the_base(world):
    view = truth_for(world, LOST_CAUSE, None, AT)
    gt = ground_truth.load(world, LOST_CAUSE)[OfferType.NUDGE]
    # 1 Dec is outside the season, so the base on the day is Ground Truth's own.
    assert view.no_offer == pytest.approx(gt.base)
    assert view.no_offer == pytest.approx(ground_truth.p_buy(gt, 0.0))
    assert view.response_class == "lost_cause" and view.options == ()


def test_each_candidate_is_priced_by_ground_truth(world):
    view = truth_for(world, LOST_CAUSE, None, AT, CANDIDATES)
    truth = ground_truth.load(world, LOST_CAUSE)
    assert [(o.offer_type, o.category) for o in view.options] == [
        (c.offer_type, c.category) for c in CANDIDATES
    ]
    pct, free, nudge = view.options
    assert pct.depth == pytest.approx(0.2) and free.depth == nudge.depth == 1.0
    assert pct.chance == pytest.approx(ground_truth.p_buy(truth[OfferType.PCT_CATEGORY], 0.2))
    assert all(o.lift == pytest.approx(o.chance - view.no_offer) for o in view.options)
    assert not any(o.chosen for o in view.options)


def test_a_sleeping_dogs_offer_chance_is_below_its_base(world):
    view = truth_for(world, SLEEPING_DOG, None, AT, CANDIDATES)
    assert view.response_class == "sleeping_dog"
    assert all(o.chance < view.no_offer for o in view.options)


def test_the_offer_replaces_its_candidate_at_its_own_terms(world):
    offer = add_offer(world, LOST_CAUSE)
    view = truth_for(world, LOST_CAUSE, offer, AT, CANDIDATES)
    chosen = [o for o in view.options if o.chosen]
    assert len(view.options) == 3 and view.options[0] is chosen[0]
    assert chosen[0].depth == pytest.approx(0.1)
    customer = outcomes.sim_customer(world, LOST_CAUSE)
    assert chosen[0].chance == pytest.approx(outcomes.buy_chance(customer, offer, load_catalog(world), AT))


def test_an_offer_outside_the_candidates_is_added_last(world):
    offer = add_offer(world, LOST_CAUSE, "points_multiplier", None, '{"multiplier": 2.0}')
    view = truth_for(world, LOST_CAUSE, offer, AT, CANDIDATES[:1])
    assert [(o.offer_type, o.chosen) for o in view.options] == [
        (OfferType.PCT_CATEGORY, False),
        (OfferType.POINTS_MULTIPLIER, True),
    ]


def test_a_customer_without_ground_truth_has_no_view(world):
    assert truth_for(world, "C99999", None, AT) is None
