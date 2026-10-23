import json
from dataclasses import FrozenInstanceError

import pytest

from offer_engine.domain import (
    LOYALTY_TIERS,
    BudgetMode,
    Chooser,
    OfferStatus,
    OfferType,
    Proposal,
    RuleSet,
    TriggerKind,
)


def test_enum_values():
    assert [t.value for t in OfferType] == [
        "pct_category",
        "flat_above_min",
        "free_shipping",
        "points_multiplier",
        "nudge",
    ]
    assert [t.value for t in TriggerKind] == [
        "cart_abandoned",
        "points_expiring",
        "long_gap",
        "first_order_delivered",
        "daily_sweep",
        "on_request",
    ]
    assert [s.value for s in OfferStatus] == [
        "queued",
        "sent",
        "claimed",
        "dismissed",
        "redeemed",
        "expired",
        "withdrawn",
    ]
    assert [c.value for c in Chooser] == ["agent", "fallback", "rules"]


def test_ruleset_defaults_named_in_ticket():
    rules = RuleSet()
    assert rules.holdout_pct == 10
    assert (rules.fatigue_dismissals, rules.fatigue_window_days, rules.fatigue_pause_days) == (3, 14, 14)
    assert rules.offer_validity_days == 3
    assert rules.shipping_fee == 40
    assert rules.point_value == 0.25
    assert rules.long_gap_days == 45
    assert rules.points_expiry_warning_days == 7
    assert rules.max_pct_by_category == {}
    assert set(rules.max_pct_by_loyalty_tier) == set(LOYALTY_TIERS)
    assert rules.budget_mode is BudgetMode.WORST_CASE


def test_ruleset_round_trips_through_json():
    rules = RuleSet(
        max_pct_by_category={"fashion": 25.0},
        margin_floor_pct=8.0,
        budget_mode=BudgetMode.EXPECTED,
        frequency_cap_count=1,
    )
    stored = json.dumps(rules.to_dict())
    assert RuleSet.from_dict(json.loads(stored)) == rules
    assert RuleSet.from_dict(RuleSet().to_dict()) == RuleSet()


def test_ruleset_to_dict_is_plain_json():
    data = RuleSet().to_dict()
    assert data["budget_mode"] == "worst_case" and type(data["budget_mode"]) is str
    assert json.loads(json.dumps(data)) == data


def test_ruleset_from_dict_fills_missing_and_coerces():
    rules = RuleSet.from_dict({"frequency_cap_count": "4", "budget_mode": "expected"})
    assert rules.frequency_cap_count == 4
    assert rules.budget_mode is BudgetMode.EXPECTED
    assert rules.weekly_budget == RuleSet().weekly_budget


def test_ruleset_from_dict_rejects_unknown_keys():
    with pytest.raises(ValueError, match="unknown Rule settings: max_bogus"):
        RuleSet.from_dict({"max_bogus": 1})


def test_to_dict_copies_dicts():
    rules = RuleSet()
    rules.to_dict()["max_pct_by_loyalty_tier"]["gold"] = 99
    assert rules.max_pct_by_loyalty_tier["gold"] != 99


def test_types_are_frozen():
    with pytest.raises(FrozenInstanceError):
        RuleSet().holdout_pct = 0
    with pytest.raises(FrozenInstanceError):
        Proposal(offer_type=None).caption = "x"


def test_no_offer_proposal():
    proposal = Proposal(offer_type=None, reason="Sure Thing")
    assert proposal.offer_type is None
    assert proposal.params == {} and proposal.featured_product_ids == ()
