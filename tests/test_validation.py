"""Validation: one test per failure code (T07, PLAN §3.5 step 3, ADR 0001)."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from offer_engine.domain import (
    BudgetState,
    Catalog,
    Category,
    Customer,
    CustomerState,
    Event,
    OfferStatus,
    OfferType,
    PastOffer,
    Product,
    Proposal,
    RuleSet,
    TriggerKind,
)
from offer_engine.rules import in_holdout
from offer_engine.validation import failed_check, no_caption_check, validate

NOW = datetime(2026, 12, 10, 10, 0)
CATALOG = Catalog(
    categories={
        "electronics": Category("electronics", margin_pct=8.0, avg_basket=4000.0),
        "fashion": Category("fashion", margin_pct=45.0, avg_basket=1500.0),
        "grocery": Category("grocery", margin_pct=15.0, avg_basket=800.0),
        "beauty": Category("beauty", margin_pct=40.0, avg_basket=700.0),
        "home": Category("home", margin_pct=30.0, avg_basket=2000.0),
    },
    products={
        p.id: p
        for p in [
            *(Product(f"F{i}", f"Fashion {i}", "fashion", 999.0) for i in (1, 2, 3)),
            *(Product(f"G{i}", f"Grocery {i}", "grocery", 199.0) for i in (1, 2)),
            Product("E1", "Electronics 1", "electronics", 4999.0),
        ]
    },
)
NO_SPEND = BudgetState(week_start=datetime(2026, 12, 7), spent=0.0, reserved=0.0)
OUT_ID = next(f"C{n:05d}" for n in range(1, 10_000) if not in_holdout(f"C{n:05d}", 10.0))
IN_ID = next(f"C{n:05d}" for n in range(1, 10_000) if in_holdout(f"C{n:05d}", 10.0))


def make_state(
    customer_id: str = OUT_ID, offers: tuple[PastOffer, ...] = (), **customer_fields
) -> CustomerState:
    """A silver Customer who viewed F1, F2 and G1 recently and F3 too long ago to count."""
    customer = Customer(
        id=customer_id,
        signup_at=customer_fields.pop("signup_at", NOW - timedelta(days=200)),
        city_tier=1,
        device="android",
        channel="organic",
        loyalty_tier="silver",
        points_balance=0,
        points_expire_at=None,
        **customer_fields,
    )
    events = (
        Event(customer_id, NOW - timedelta(days=5), "product_view", "fashion", "F1"),
        Event(customer_id, NOW - timedelta(days=10), "product_view", "fashion", "F2"),
        Event(customer_id, NOW - timedelta(days=100), "product_view", "fashion", "F3"),
        Event(customer_id, NOW - timedelta(days=3), "cart_add", "grocery", "G1"),
    )
    return CustomerState(customer=customer, events=events, offers=offers)


def past_offer(days_ago: float, status=OfferStatus.SENT, redeemed_days_ago: float | None = None) -> PastOffer:
    created = NOW - timedelta(days=days_ago)
    return PastOffer(
        id=int(days_ago * 100),
        offer_type=OfferType.NUDGE,
        category=None,
        status=status,
        created_at=created,
        expires_at=created + timedelta(days=3),
        redeemed_at=None if redeemed_days_ago is None else NOW - timedelta(days=redeemed_days_ago),
    )


VALID = Proposal(
    offer_type=OfferType.PCT_CATEGORY,
    category="fashion",
    params={"pct": 15.0, "cap": 300.0},
    featured_product_ids=("F1",),
    send_at=NOW + timedelta(hours=1),
    caption="Fresh picks in fashion, just for you.",
    reason="Viewed fashion twice this fortnight.",
)


def check(
    proposal=VALID,
    state=None,
    rules=None,
    budget=NO_SPEND,
    now=NOW,
    caption_checker=no_caption_check,
    trigger=TriggerKind.CART_ABANDONED,
):
    return validate(
        proposal, state or make_state(), rules or RuleSet(), budget, now, CATALOG, caption_checker, trigger
    )


def codes(result) -> list[str]:
    return [f.split(":", 1)[0] for f in result.failures]


def failure(result, code: str) -> str:
    matches = [f for f in result.failures if f.startswith(f"{code}:")]
    assert len(matches) == 1, f"expected one {code} failure in {result.failures}"
    return matches[0]


def assert_only(result, code: str) -> str:
    assert result.ok is False
    assert codes(result) == [code], result.failures
    return result.failures[0]


# --- Passing proposals -------------------------------------------------------------------------


def test_valid_proposal_passes():
    result = check()
    assert result.ok is True and result.failures == ()


@pytest.mark.parametrize(
    "proposal",
    [
        replace(VALID, category="grocery", params={"pct": 10.0, "cap": 50.0}, featured_product_ids=("G1",)),
        replace(
            VALID,
            offer_type=OfferType.FLAT_ABOVE_MIN,
            category=None,
            params={"amount": 100.0, "min_basket": 5000.0},
        ),
        replace(VALID, offer_type=OfferType.FREE_SHIPPING, category=None, params={}),
        replace(VALID, offer_type=OfferType.POINTS_MULTIPLIER, category=None, params={"multiplier": 2.0}),
        replace(
            VALID, offer_type=OfferType.NUDGE, category=None, params={}, featured_product_ids=("F1", "G1")
        ),
        replace(VALID, featured_product_ids=()),
        replace(VALID, send_at=NOW),
    ],
    ids=["pct-grocery", "flat", "free-shipping", "points", "nudge-any-category", "no-featured", "send-now"],
)
def test_every_offer_type_can_pass(proposal):
    result = check(proposal)
    assert result.ok is True, result.failures


def test_params_at_their_bounds_pass():
    assert check(replace(VALID, params={"pct": 20.0, "cap": 500.0})).ok
    assert check(replace(VALID, params={"pct": 5.0, "cap": 50.0})).ok


@pytest.mark.parametrize(
    "state",
    [
        make_state(opted_out=True),
        make_state(IN_ID),
        make_state(offers=(past_offer(1), past_offer(2))),
    ],
    ids=["opted-out", "holdout", "frequency-cap"],
)
def test_no_offer_is_always_valid(state):
    no_offer = Proposal(offer_type=None)
    assert check(no_offer, state=state).ok is True
    assert check(no_offer, budget=replace(NO_SPEND, spent=1e9), now=NOW.replace(hour=23)).ok is True


# --- Short-circuits ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "name", "rule"),
    [
        (make_state(opted_out=True), "opt_out", "opt_out"),
        (make_state(IN_ID), "holdout", "holdout_pct"),
        (
            make_state(offers=tuple(past_offer(d, OfferStatus.DISMISSED) for d in (8, 9, 10))),
            "fatigue_pause",
            "fatigue_dismissals",
        ),
        (make_state(offers=(past_offer(1), past_offer(2))), "frequency_cap", "frequency_cap_count"),
        (
            make_state(offers=(past_offer(20, OfferStatus.REDEEMED, 3),)),
            "cooldown",
            "cooldown_days_after_redemption",
        ),
        (make_state(signup_at=NOW - timedelta(hours=3)), "eligibility", "min_days_since_signup"),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_short_circuit_fails_with_its_rule(state, name, rule):
    text = assert_only(check(state=state), "short_circuit")
    assert text == f"short_circuit: {name} ({rule})"


def test_short_circuit_still_reports_proposal_faults():
    result = check(replace(VALID, caption="", featured_product_ids=("F3",)), state=make_state(opted_out=True))
    assert codes(result) == ["short_circuit", "featured_not_seen", "caption_missing"]


# --- Offer Type and category -------------------------------------------------------------------


def test_offer_type_dropped_from_eligible_set():
    proposal = replace(
        VALID,
        offer_type=OfferType.FLAT_ABOVE_MIN,
        category=None,
        params={"amount": 100.0, "min_basket": 5000.0},
    )
    text = assert_only(check(proposal, rules=RuleSet(max_flat_amount=10.0)), "offer_type_not_eligible")
    assert text == "offer_type_not_eligible: flat_above_min (max_flat_amount)"


def test_pct_category_with_no_recent_category_is_not_eligible():
    state = replace(make_state(), events=())
    result = check(replace(VALID, featured_product_ids=()), state=state)
    text = assert_only(result, "offer_type_not_eligible")
    assert "pct_category" in text


def test_category_not_seen_recently():
    proposal = replace(VALID, category="electronics", featured_product_ids=())
    text = assert_only(check(proposal), "category_not_eligible")
    assert "electronics" in text and "not in the Eligible Set" in text


def test_category_dropped_names_its_rule():
    proposal = replace(VALID, category="grocery", params={"pct": 5.0, "cap": 100.0}, featured_product_ids=())
    text = assert_only(check(proposal, rules=RuleSet(margin_floor_pct=12.0)), "category_not_eligible")
    assert text.endswith("(margin_floor_pct)")


def test_category_given_for_a_type_without_one():
    proposal = replace(VALID, offer_type=OfferType.FREE_SHIPPING, params={})
    text = assert_only(check(proposal), "category_not_eligible")
    assert "free_shipping" in text


def test_unknown_category():
    proposal = replace(VALID, category="toys", featured_product_ids=())
    assert_only(check(proposal), "category_not_eligible")


# --- Parameters --------------------------------------------------------------------------------


def test_param_missing():
    text = assert_only(check(replace(VALID, params={"pct": 15.0})), "param_missing")
    assert text == "param_missing: cap"


def test_param_extra():
    text = assert_only(check(replace(VALID, params={"pct": 15.0, "cap": 300.0, "bonus": 1.0})), "param_extra")
    assert text == "param_extra: bonus"


def test_param_above_range_names_its_binding_rule():
    text = assert_only(check(replace(VALID, params={"pct": 25.0, "cap": 300.0})), "param_out_of_range")
    assert text == "param_out_of_range: pct=25 > 20 (max_pct_by_loyalty_tier)"


def test_param_below_range():
    text = assert_only(check(replace(VALID, params={"pct": 2.0, "cap": 300.0})), "param_out_of_range")
    assert text == "param_out_of_range: pct=2 < 5 (minimum)"


def test_min_basket_below_range_names_the_margin_floor():
    proposal = replace(
        VALID,
        offer_type=OfferType.FLAT_ABOVE_MIN,
        category=None,
        params={"amount": 100.0, "min_basket": 100.0},
    )
    text = assert_only(check(proposal), "param_out_of_range")
    assert text.startswith("param_out_of_range: min_basket=100 <") and text.endswith("(margin_floor_pct)")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_param_is_out_of_range(bad):
    result = check(replace(VALID, params={"pct": bad, "cap": 300.0}))
    assert result.ok is False and "param_out_of_range" in codes(result)


def test_infinite_min_basket_is_out_of_range():
    proposal = replace(
        VALID,
        offer_type=OfferType.FLAT_ABOVE_MIN,
        category=None,
        params={"amount": 100.0, "min_basket": float("inf")},
    )
    assert_only(check(proposal), "param_out_of_range")


def test_every_bad_param_is_reported():
    result = check(replace(VALID, params={"pct": 99.0, "bonus": 1.0}))
    assert sorted(codes(result)) == ["param_extra", "param_missing", "param_out_of_range"]


# --- Cost --------------------------------------------------------------------------------------


def test_cost_over_per_offer_cost_cap():
    result = check(replace(VALID, params={"pct": 15.0, "cap": 600.0}))
    assert sorted(codes(result)) == ["cost_over_cap", "param_out_of_range"]
    assert failure(result, "cost_over_cap") == "cost_over_cap: ₹600 > ₹500 (per_offer_cost_cap)"
    assert failure(result, "param_out_of_range").endswith("(per_offer_cost_cap)")


def test_cost_over_remaining_budget():
    budget = replace(NO_SPEND, spent=49_700.0, reserved=100.0)
    result = check(budget=budget)
    assert sorted(codes(result)) == ["over_budget", "param_out_of_range"]
    assert failure(result, "over_budget") == "over_budget: ₹300 > ₹200 left (weekly_budget)"


def test_budget_is_rechecked_not_trusted():
    """The same proposal fails once the budget runs out, without anyone handing Validation a new Eligible Set."""
    assert check().ok
    spent = check(budget=replace(NO_SPEND, spent=50_000.0))
    assert "weekly_budget" in " ".join(spent.failures)


# --- Send time ---------------------------------------------------------------------------------


def test_send_at_missing():
    assert_only(check(replace(VALID, send_at=None)), "send_at_missing")


@pytest.mark.parametrize(
    ("send_at", "rule"),
    [
        (NOW - timedelta(minutes=1), "in the past"),
        (NOW.replace(hour=21), "send_hour_end"),
        (NOW.replace(hour=23), "send_hour_end"),
        (NOW + timedelta(days=1, hours=-2), "send_hour_start"),
        (NOW + timedelta(hours=23), "send_window"),
        (NOW + timedelta(days=2), "max_send_delay_hours"),
    ],
    ids=["past", "at-window-end", "late-evening", "next-dawn", "next-day-in-hours", "beyond-delay"],
)
def test_send_at_outside_window(send_at, rule):
    text = assert_only(check(replace(VALID, send_at=send_at)), "send_at_outside_window")
    assert text.endswith(f"({rule})")


def test_no_send_window_left():
    rules = RuleSet(send_hour_start=12, send_hour_end=13, max_send_delay_hours=1)
    text = assert_only(check(rules=rules), "send_at_outside_window")
    assert "no send window" in text


# --- Featured products -------------------------------------------------------------------------


def test_featured_unknown():
    text = assert_only(check(replace(VALID, featured_product_ids=("P404",))), "featured_unknown")
    assert text == "featured_unknown: P404"


def test_featured_in_another_category():
    text = assert_only(check(replace(VALID, featured_product_ids=("G1",))), "featured_wrong_category")
    assert text == "featured_wrong_category: G1 is grocery, not fashion"


@pytest.mark.parametrize("product_id", ["F3", "E1"], ids=["seen-too-long-ago", "never-seen"])
def test_featured_not_in_the_customers_recent_events(product_id):
    proposal = replace(VALID, featured_product_ids=(product_id,))
    if product_id == "E1":
        proposal = replace(proposal, offer_type=OfferType.NUDGE, category=None, params={})
    text = assert_only(check(proposal), "featured_not_seen")
    assert text.startswith(f"featured_not_seen: {product_id}")


def test_featured_from_someone_elses_events():
    state = make_state()
    other = Event("C99999", NOW - timedelta(days=1), "product_view", "fashion", "F3")
    state = replace(state, events=(*state.events, other))
    assert_only(check(replace(VALID, featured_product_ids=("F3",)), state=state), "featured_not_seen")


def test_too_many_featured():
    nudge = replace(
        VALID, offer_type=OfferType.NUDGE, category=None, params={}, featured_product_ids=("F1", "F2", "G1")
    )
    text = assert_only(check(nudge), "too_many_featured")
    assert text == "too_many_featured: 3 > 2"


# --- Caption and reason ------------------------------------------------------------------------


@pytest.mark.parametrize("caption", ["", "   \n"])
def test_caption_missing(caption):
    assert_only(check(replace(VALID, caption=caption)), "caption_missing")


@pytest.mark.parametrize("reason", ["", "  "])
def test_reason_missing(reason):
    assert_only(check(replace(VALID, reason=reason)), "reason_missing")


def test_caption_checker_failures_are_added():
    seen = []

    def checker(caption, proposal, catalog):
        seen.append((caption, proposal, catalog))
        return ["caption_number_mismatch: says 50% but the Offer is 15%"]

    result = check(caption_checker=checker)
    assert result.failures == ("caption_number_mismatch: says 50% but the Offer is 15%",)
    assert seen == [(VALID.caption, VALID, CATALOG)]


def test_caption_checker_skipped_for_an_empty_caption():
    def checker(caption, proposal, catalog):
        raise AssertionError("called")

    assert_only(check(replace(VALID, caption=""), caption_checker=checker), "caption_missing")


def test_no_caption_check_passes_anything():
    assert no_caption_check("50% off, today only!!!", VALID, CATALOG) == []


# --- All failures ------------------------------------------------------------------------------


def test_reports_every_failure_not_just_the_first():
    proposal = replace(
        VALID,
        params={"pct": 25.0, "cap": 300.0},
        send_at=NOW - timedelta(hours=1),
        featured_product_ids=("P404", "G1", "F3"),
        caption="",
        reason="",
    )
    assert codes(check(proposal)) == [
        "param_out_of_range",
        "send_at_outside_window",
        "too_many_featured",
        "featured_unknown",
        "featured_wrong_category",
        "featured_not_seen",
        "caption_missing",
        "reason_missing",
    ]


# --- Checks run (T35) --------------------------------------------------------------------------

ALL_CHECKS = (
    "short_circuit",
    "offer_type",
    "params",
    "cost_cap",
    "budget",
    "send_window",
    "featured",
    "caption",
    "reason",
    "caption_check",
)


def test_checks_names_every_check_on_a_valid_proposal():
    result = check()
    assert result.ok and result.checks == ALL_CHECKS


def test_checks_are_the_same_when_the_proposal_fails():
    proposal = replace(VALID, params={"pct": 25.0, "cap": 300.0}, featured_product_ids=("P404",))
    result = check(proposal)
    assert not result.ok and result.checks == ALL_CHECKS


def test_no_offer_runs_no_checks():
    assert check(Proposal(None, reason="nothing pays")).checks == ()


def test_short_circuit_skips_the_option_checks():
    result = check(state=make_state(IN_ID))
    assert result.checks == ("short_circuit", "featured", "caption", "reason", "caption_check")


def test_unknown_option_skips_params_and_cost():
    result = check(replace(VALID, category="toys"))
    assert result.checks == (
        "short_circuit",
        "offer_type",
        "send_window",
        "featured",
        "caption",
        "reason",
        "caption_check",
    )


def test_empty_caption_skips_the_caption_check():
    result = check(replace(VALID, caption=""))
    assert "caption" in result.checks and "caption_check" not in result.checks


def test_every_failure_belongs_to_a_check_that_ran():
    def checker(caption, proposal, catalog):
        return ["invented_urgency: hurry"]

    proposal = replace(
        VALID,
        params={"pct": 25.0, "cap": 300.0},
        send_at=NOW - timedelta(hours=1),
        featured_product_ids=("P404", "G1", "F3"),
        reason="",
    )
    result = check(proposal, budget=replace(NO_SPEND, spent=49_800.0), caption_checker=checker)
    assert {failed_check(f) for f in result.failures} == {
        "params",
        "budget",
        "send_window",
        "featured",
        "reason",
        "caption_check",
    }
    assert all(failed_check(f) in result.checks for f in result.failures)


NUDGE = replace(VALID, offer_type=OfferType.NUDGE, category=None, params={})


@pytest.mark.parametrize("trigger", [TriggerKind.CART_ABANDONED, TriggerKind.POINTS_EXPIRING])
def test_a_nudge_on_a_reminder_trigger_passes(trigger):
    assert check(NUDGE, trigger=trigger).ok


@pytest.mark.parametrize(
    "trigger",
    [
        TriggerKind.DAILY_SWEEP,
        TriggerKind.LONG_GAP,
        TriggerKind.FIRST_ORDER_DELIVERED,
        TriggerKind.ON_REQUEST,
        None,
    ],
)
def test_a_nudge_with_nothing_to_remind_about_fails(trigger):
    """QnA Q56: the agent may not send a Nudge on the Daily Sweep, a long gap, a first delivery or /offers."""
    result = check(NUDGE, trigger=trigger)
    assert result.ok is False
    assert (
        failure(result, "offer_type_not_eligible") == "offer_type_not_eligible: nudge (nudge_needs_reminder)"
    )


def test_a_paid_offer_on_the_daily_sweep_still_passes():
    assert check(trigger=TriggerKind.DAILY_SWEEP).ok
