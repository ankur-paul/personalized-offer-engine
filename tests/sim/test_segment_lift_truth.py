"""Estimated Lift v1 (T16) against Ground Truth on a 5,000-Customer world. Tests may read `sim_*`; the fit may not."""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pytest

from offer_engine import clock
from offer_engine.customers import load_customer_states
from offer_engine.domain import OfferType
from offer_engine.lift import segment_lift
from offer_engine.sim import ground_truth

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def world_5k(tmp_path_factory):
    from offer_engine.db import connect
    from offer_engine.sim.generate import run

    conn = connect(tmp_path_factory.mktemp("5k") / "world.db")
    run(conn, 5_000, months=12, seed=7)
    segment_lift.fit(conn)
    yield conn
    conn.close()


def test_segment_estimates_follow_ground_truth_lift(world_5k):
    conn = world_5k
    gts = ground_truth.load_all(conn)
    ids = [r[0] for r in conn.execute("SELECT id FROM customers")]
    true_lift = defaultdict(list)
    for cid, state in load_customer_states(conn, ids, clock.START).items():
        segment = segment_lift.segment_of(state, clock.START)
        for offer_type, gt in gts[cid].items():
            true_lift[(segment, offer_type)].append(gt.max_lift)

    estimated, truth = [], []
    query = (
        "SELECT offer_type, loyalty_tier, recency, coupon_user, estimated_lift FROM lift_estimates"
        " WHERE loyalty_tier IS NOT NULL AND from_type_avg = 0"
    )
    for offer_type, tier, recency, coupon_user, lift in conn.execute(query):
        key = ((tier, recency, bool(coupon_user)), OfferType(offer_type))
        if key in true_lift:
            estimated.append(lift)
            truth.append(np.mean(true_lift[key]))
    assert len(estimated) >= 50
    assert np.corrcoef(estimated, truth)[0, 1] > 0


def test_offer_type_averages_match_ground_truth_at_the_history_moments(world_5k):
    """Pooled over every segment the noise averages out. The truth is T14's own: mean `p_buy` at the moments that
    got an Offer of the type minus mean `p_buy` at the moments that got none, within 1 point."""
    no_offer = world_5k.execute(
        "SELECT AVG(p_buy) FROM sim_history_moments WHERE offer_id IS NULL"
    ).fetchone()[0]
    truth = {
        offer_type: p - no_offer
        for offer_type, p in world_5k.execute(
            "SELECT o.offer_type, AVG(m.p_buy) FROM sim_history_moments m JOIN offers o ON o.id = m.offer_id"
            " GROUP BY o.offer_type"
        )
    }
    for offer_type, lift in world_5k.execute(
        "SELECT offer_type, observed_lift FROM lift_estimates WHERE loyalty_tier IS NULL"
    ):
        assert lift == pytest.approx(truth[offer_type], abs=0.01), offer_type
