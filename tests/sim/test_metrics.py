"""Offline Policy metrics (T26) on hand-built runs."""

from datetime import datetime

import pytest

from offer_engine.domain import OfferType
from offer_engine.sim.metrics import incremental_margin, lift_deciles, spend, summarise
from offer_engine.sim.offline import OfferRecord, PolicyResult

START = datetime(2026, 12, 1)


def result(policy, margin, offers=(), **kw):
    return PolicyResult(policy, START, 28, 7, dict(margin), list(offers), **kw)


def offer(cid, cost=0.0, *, redeemed=None, sure=False, est=None, true=None, sent=True, claimed=None):
    redeemed = cost > 0 if redeemed is None else redeemed
    return OfferRecord(
        cid,
        OfferType.PCT_CATEGORY,
        sent,
        redeemed if claimed is None else claimed,
        redeemed,
        cost,
        sure,
        est,
        true,
    )


BASELINE = result("no_offers", {"a": 100.0, "b": 50.0, "c": 0.0})


def test_incremental_margin_is_the_difference_from_no_offers_on_the_same_customers():
    policy = result("rules_only", {"a": 130.0, "b": 40.0, "c": 25.0})
    assert incremental_margin(policy, BASELINE, ["a", "b", "c"]) == pytest.approx(45.0)
    assert incremental_margin(policy, BASELINE, ["a"]) == pytest.approx(30.0)
    assert incremental_margin(BASELINE, BASELINE, ["a", "b", "c"]) == 0


def test_the_baseline_must_share_start_days_and_seed():
    other = PolicyResult("rules_only", START, 7, 7, {"a": 1.0})
    with pytest.raises(ValueError):
        incremental_margin(other, BASELINE, ["a"])


def test_spend_counts_redemptions_and_sure_things_separately():
    offers = [offer("a", 60.0, sure=True), offer("b", 40.0), offer("c"), offer("a", 25.0, sure=True)]
    assert spend(offers) == pytest.approx(125.0)
    assert spend(offers, sure_things_only=True) == pytest.approx(85.0)


def test_summarise_scores_per_rupee_on_the_chosen_customers():
    offers = [offer("a", 20.0, sure=True), offer("b", 10.0), offer("c", claimed=True), offer("c", sent=False)]
    policy = result("rules_only", {"a": 130.0, "b": 40.0, "c": 0.0}, offers)
    policy.rejections.update({"a": 2, "c": 1})
    policy.fallbacks.update({"c": 3})

    m = summarise(policy, BASELINE, ["a", "b", "c"], "population")
    assert (m.customers, m.offers_sent, m.claimed, m.redeemed) == (3, 3, 3, 2)
    assert m.spend == 30.0 and m.incremental_margin == 20.0 and m.per_rupee == pytest.approx(20 / 30)
    assert m.sure_thing_spend == 20.0 and m.validation_rejections == 3 and m.fallbacks == 3

    sample = summarise(policy, BASELINE, ["a"], "sample")
    assert (sample.customers, sample.spend, sample.incremental_margin, sample.validation_rejections) == (
        1,
        20,
        30,
        2,
    )


def test_no_spend_has_no_per_rupee():
    assert summarise(BASELINE, BASELINE, ["a", "b", "c"], "population").per_rupee is None


def test_lift_deciles_group_sent_offers_by_estimated_lift():
    offers = [offer(f"c{i}", est=i / 100, true=i / 200) for i in range(20)]
    offers += [
        offer("x", est=None, true=0.5),
        offer("y", est=0.9, true=None),
        offer("z", est=0.9, true=0.9, sent=False),
    ]
    deciles = lift_deciles(offers)
    assert [d.decile for d in deciles] == list(range(1, 11))
    assert all(d.offers == 2 for d in deciles)
    assert deciles[0].estimated_lift == pytest.approx(0.005) and deciles[0].true_lift == pytest.approx(0.0025)
    assert deciles[-1].estimated_lift == pytest.approx(0.185)
    assert [d.true_lift for d in deciles] == sorted(d.true_lift for d in deciles)


def test_fewer_offers_than_deciles_make_fewer_groups():
    assert len(lift_deciles([offer("a", est=0.1, true=0.1), offer("b", est=0.2, true=0.0)])) == 2
    assert lift_deciles([]) == ()
