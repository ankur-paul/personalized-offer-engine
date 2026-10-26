"""Rules engine: Eligible Set, Binding Rules and short-circuits (T06, PLAN §3.3, §3.5 step 1)."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from offer_engine.cli import main
from offer_engine.domain import (
    BudgetState,
    Catalog,
    Category,
    Customer,
    CustomerState,
    Event,
    OfferStatus,
    OfferType,
    ParamRange,
    PastOffer,
    RuleSet,
    TriggerKind,
)
from offer_engine.rules import (
    MIN_CAP,
    MIN_FLAT_AMOUNT,
    MIN_PCT,
    MIN_POINTS_MULTIPLIER,
    NUDGE_TRIGGERS,
    POINTS_PER_RUPEE,
    eligible_set,
    empty_set_binding,
    fatigue_paused_until,
    in_holdout,
    offer_cost,
)

NOW = datetime(2026, 12, 10, 10, 0)
CATALOG = Catalog(
    categories={
        "electronics": Category("electronics", margin_pct=8.0, avg_basket=4000.0),
        "fashion": Category("fashion", margin_pct=45.0, avg_basket=1500.0),
        "grocery": Category("grocery", margin_pct=15.0, avg_basket=800.0),
        "beauty": Category("beauty", margin_pct=40.0, avg_basket=700.0),
        "home": Category("home", margin_pct=30.0, avg_basket=2000.0),
    },
    products={},
)
AVG_MARGIN = (8 + 45 + 15 + 40 + 30) / 5
AVG_BASKET = (4000 + 1500 + 800 + 700 + 2000) / 5
NO_SPEND = BudgetState(week_start=datetime(2026, 12, 7), spent=0.0, reserved=0.0)


def first_id(in_or_out: bool, pct: float = 10.0) -> str:
    return next(f"C{n:05d}" for n in range(1, 10_000) if in_holdout(f"C{n:05d}", pct) is in_or_out)


OUT_ID = first_id(False)
IN_ID = first_id(True)


def make_state(
    customer_id: str = OUT_ID,
    tier: str = "silver",
    categories: tuple[str, ...] = ("fashion",),
    offers: tuple[PastOffer, ...] = (),
    **customer_fields,
) -> CustomerState:
    customer = Customer(
        id=customer_id,
        signup_at=customer_fields.pop("signup_at", NOW - timedelta(days=200)),
        city_tier=1,
        device="android",
        channel="organic",
        loyalty_tier=tier,
        points_balance=0,
        points_expire_at=None,
        **customer_fields,
    )
    events = tuple(
        Event(customer_id, NOW - timedelta(days=5 + i), "product_view", category=cat)
        for i, cat in enumerate(categories)
    )
    return CustomerState(customer=customer, events=events, offers=offers)


def past_offer(
    days_ago: float, status: OfferStatus = OfferStatus.SENT, redeemed_days_ago: float | None = None
) -> PastOffer:
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


def dismissed(*days_ago: float) -> tuple[PastOffer, ...]:
    return tuple(past_offer(d, OfferStatus.DISMISSED) for d in days_ago)


def compute(state=None, rules=None, budget=NO_SPEND, now=NOW, trigger=TriggerKind.CART_ABANDONED):
    """An abandoned cart by default, so every Offer Type, the Nudge too, can be eligible."""
    return eligible_set(state or make_state(), rules or RuleSet(), budget, now, CATALOG, trigger)


def option(es, offer_type, category=None):
    matches = [o for o in es.options if o.offer_type == offer_type and o.category == category]
    assert len(matches) == 1, f"no single {offer_type} {category} option in {es.options}"
    return matches[0]


def offer_types(es):
    return {(o.offer_type, o.category) for o in es.options}


# --- Short-circuits ----------------------------------------------------------------------------


def test_all_rules_pass_gives_every_offer_type():
    es = compute()
    assert es.short_circuit is None and es.binding_rule is None
    assert offer_types(es) == {
        (OfferType.PCT_CATEGORY, "fashion"),
        (OfferType.FLAT_ABOVE_MIN, None),
        (OfferType.FREE_SHIPPING, None),
        (OfferType.POINTS_MULTIPLIER, None),
        (OfferType.NUDGE, None),
    }
    assert es.customer_id == OUT_ID and es.at == NOW


@pytest.mark.parametrize("trigger", list(TriggerKind))
def test_a_nudge_is_eligible_only_on_a_reminder_trigger(trigger):
    """A Nudge reminds of something: an abandoned cart or expiring points (GLOSSARY, QnA Q56)."""
    es = compute(trigger=trigger)
    has_nudge = (OfferType.NUDGE, None) in offer_types(es)
    assert has_nudge == (trigger in {TriggerKind.CART_ABANDONED, TriggerKind.POINTS_EXPIRING})
    if has_nudge:
        assert "nudge" not in es.dropped
    else:
        assert es.dropped["nudge"] == "nudge_needs_reminder"
    assert {o.offer_type for o in es.options} - {OfferType.NUDGE} == {
        OfferType.PCT_CATEGORY,
        OfferType.FLAT_ABOVE_MIN,
        OfferType.FREE_SHIPPING,
        OfferType.POINTS_MULTIPLIER,
    }


def test_the_reminder_triggers_are_cart_and_points():
    assert NUDGE_TRIGGERS == {TriggerKind.CART_ABANDONED, TriggerKind.POINTS_EXPIRING}


def test_no_trigger_means_no_nudge():
    es = compute(trigger=None)
    assert (OfferType.NUDGE, None) not in offer_types(es) and es.dropped["nudge"] == "nudge_needs_reminder"


def test_opt_out_short_circuits():
    es = compute(make_state(opted_out=True))
    assert (es.short_circuit, es.binding_rule) == ("opt_out", "opt_out")
    assert es.options == () and es.send_window is None


def test_opt_out_beats_everything():
    state = make_state(
        IN_ID,
        opted_out=True,
        signup_at=NOW - timedelta(hours=1),
        offers=dismissed(1, 2, 3) + (past_offer(4, OfferStatus.REDEEMED, redeemed_days_ago=1),),
    )
    assert compute(state).short_circuit == "opt_out"


def test_holdout_short_circuits_and_beats_later_checks():
    es = compute(make_state(IN_ID, offers=dismissed(1, 2, 3)))
    assert (es.short_circuit, es.binding_rule) == ("holdout", "holdout_pct")
    assert es.options == ()


def test_fatigue_pause_after_three_dismissals_in_window():
    state = make_state(offers=dismissed(10, 6, 2))
    rules = RuleSet()
    assert fatigue_paused_until(state, rules) == NOW - timedelta(days=2) + timedelta(days=14)
    es = compute(state)
    assert (es.short_circuit, es.binding_rule) == ("fatigue_pause", "fatigue_dismissals")


def test_fatigue_pause_lasts_from_the_last_dismissal_after_the_window_passes():
    # Dismissals on days 0, 1, 2 pause until day 16, even though day 0 left the 14-day window on day 14.
    state = make_state(offers=dismissed(15, 14, 13))
    assert fatigue_paused_until(state, RuleSet()) == NOW + timedelta(days=1)
    assert compute(state).short_circuit == "fatigue_pause"


def test_no_fatigue_pause_when_dismissals_are_spread_out_or_too_few():
    assert fatigue_paused_until(make_state(offers=dismissed(30, 15, 1)), RuleSet()) is None
    assert fatigue_paused_until(make_state(offers=dismissed(2, 1)), RuleSet()) is None


def test_fatigue_pause_ends():
    state = make_state(offers=dismissed(20, 19, 18))
    assert fatigue_paused_until(state, RuleSet()) == NOW - timedelta(days=4)
    assert compute(state).short_circuit is None


def test_fatigue_settings_are_rules():
    state = make_state(offers=dismissed(9, 2))  # 7 days apart; only one inside the frequency cap
    assert compute(state, RuleSet(fatigue_dismissals=2)).short_circuit == "fatigue_pause"
    assert compute(state, RuleSet(fatigue_dismissals=2, fatigue_window_days=6)).short_circuit is None
    assert compute(state, RuleSet(fatigue_dismissals=2, fatigue_pause_days=1)).short_circuit is None


def test_frequency_cap():
    es = compute(make_state(offers=(past_offer(1), past_offer(6))))
    assert (es.short_circuit, es.binding_rule) == ("frequency_cap", "frequency_cap_count")
    assert compute(make_state(offers=(past_offer(1), past_offer(8)))).short_circuit is None
    assert compute(make_state(offers=(past_offer(1),)), RuleSet(frequency_cap_count=1)).short_circuit == (
        "frequency_cap"
    )


def test_fatigue_pause_beats_frequency_cap():
    assert compute(make_state(offers=dismissed(3, 2, 1))).short_circuit == "fatigue_pause"


def test_cooldown_after_redemption():
    redeemed = past_offer(10, OfferStatus.REDEEMED, redeemed_days_ago=3)
    es = compute(make_state(offers=(redeemed,)))
    assert (es.short_circuit, es.binding_rule) == ("cooldown", "cooldown_days_after_redemption")
    old = past_offer(12, OfferStatus.REDEEMED, redeemed_days_ago=8)
    assert compute(make_state(offers=(old,))).short_circuit is None


def test_eligibility_min_days_since_signup():
    es = compute(make_state(signup_at=NOW - timedelta(hours=12)))
    assert (es.short_circuit, es.binding_rule) == ("eligibility", "min_days_since_signup")
    assert compute(make_state(signup_at=NOW - timedelta(days=1))).short_circuit is None


def test_cooldown_beats_eligibility():
    state = make_state(
        signup_at=NOW - timedelta(hours=12),
        offers=(past_offer(1, OfferStatus.REDEEMED, redeemed_days_ago=0.1),),
    )
    assert compute(state).short_circuit == "cooldown"


# --- Holdout -----------------------------------------------------------------------------------


def test_holdout_is_deterministic():
    assert [in_holdout(f"C{n:05d}", 10.0) for n in range(200)] == [
        in_holdout(f"C{n:05d}", 10.0) for n in range(200)
    ]


def test_holdout_share_is_about_the_setting():
    share = sum(in_holdout(f"C{n:05d}", 10.0) for n in range(1, 10_001)) / 10_000
    assert 0.09 <= share <= 0.11


def test_holdout_extremes():
    assert not any(in_holdout(f"C{n:05d}", 0.0) for n in range(500))
    assert all(in_holdout(f"C{n:05d}", 100.0) for n in range(500))


def test_tester_copy_shares_its_source_holdout():
    assert in_holdout(f"{IN_ID}-t123456789", 10.0)
    assert not in_holdout(f"{OUT_ID}-t123456789", 10.0)
    assert compute(make_state(f"{IN_ID}-t42")).short_circuit == "holdout"


def test_holdout_pct_is_a_rule():
    assert compute(make_state(IN_ID), RuleSet(holdout_pct=0.0)).short_circuit is None


# --- % off a category --------------------------------------------------------------------------


def test_pct_category_one_option_per_recent_category():
    state = make_state(categories=("fashion", "beauty", "fashion"))
    old = Event(OUT_ID, NOW - timedelta(days=91), "order", category="home")
    unknown = Event(OUT_ID, NOW - timedelta(days=1), "product_view", category="toys")
    future = Event(OUT_ID, NOW + timedelta(days=1), "product_view", category="grocery")
    no_cat = Event(OUT_ID, NOW - timedelta(days=1), "session")
    state = replace(state, events=state.events + (old, unknown, future, no_cat))
    cats = sorted(o.category for o in compute(state).options if o.offer_type == OfferType.PCT_CATEGORY)
    assert cats == ["beauty", "fashion"]


def test_pct_bound_by_loyalty_tier():
    opt = option(compute(), OfferType.PCT_CATEGORY, "fashion")
    assert opt.ranges["pct"] == ParamRange(MIN_PCT, 20.0)
    assert opt.binding_rules["pct"] == "max_pct_by_loyalty_tier"


def test_pct_bound_by_category_cap():
    opt = option(
        compute(rules=RuleSet(max_pct_by_category={"fashion": 12.0})), OfferType.PCT_CATEGORY, "fashion"
    )
    assert opt.ranges["pct"].hi == 12.0
    assert opt.binding_rules["pct"] == "max_pct_by_category"


def test_pct_bound_by_margin_floor():
    opt = option(compute(make_state(categories=("grocery",))), OfferType.PCT_CATEGORY, "grocery")
    assert opt.ranges["pct"] == ParamRange(MIN_PCT, 10.0)
    assert opt.binding_rules["pct"] == "margin_floor_pct"


@pytest.mark.parametrize(
    ("cat_cap", "tier", "floor", "expected_hi", "expected_rule"),
    [
        (25.0, "bronze", 5.0, 15.0, "max_pct_by_loyalty_tier"),  # tier 15 < category 25 < margin room 40
        (12.0, "platinum", 5.0, 12.0, "max_pct_by_category"),  # category 12 < tier 30 < margin room 40
        (30.0, "platinum", 30.0, 15.0, "margin_floor_pct"),  # margin room 15 < category 30 = tier 30
        (8.0, "bronze", 38.0, 7.0, "margin_floor_pct"),  # all three bind; margin room 7 is strictest
    ],
)
def test_pct_strictest_rule_wins(cat_cap, tier, floor, expected_hi, expected_rule):
    rules = RuleSet(max_pct_by_category={"fashion": cat_cap}, margin_floor_pct=floor)
    opt = option(compute(make_state(tier=tier), rules), OfferType.PCT_CATEGORY, "fashion")
    assert opt.ranges["pct"].hi == expected_hi
    assert opt.binding_rules["pct"] == expected_rule


def test_pct_empty_range_is_dropped_with_its_rule():
    es = compute(make_state(categories=("electronics", "fashion")))  # electronics: 8% margin − 5% floor = 3%
    assert (OfferType.PCT_CATEGORY, "electronics") not in offer_types(es)
    assert es.dropped["pct_category:electronics"] == "margin_floor_pct"
    es = compute(rules=RuleSet(max_pct_by_category={"fashion": 4.0}))
    assert es.dropped["pct_category:fashion"] == "max_pct_by_category"


def test_pct_cap_bound_by_per_offer_cost_cap_or_budget():
    opt = option(compute(), OfferType.PCT_CATEGORY, "fashion")
    assert opt.ranges["cap"] == ParamRange(MIN_CAP, 500.0)
    assert opt.binding_rules["cap"] == "per_offer_cost_cap"
    assert opt.worst_case_cost == 500.0

    budget = BudgetState(week_start=NO_SPEND.week_start, spent=49_000.0, reserved=800.0)
    opt = option(compute(budget=budget), OfferType.PCT_CATEGORY, "fashion")
    assert opt.ranges["cap"].hi == 200.0
    assert opt.binding_rules["cap"] == "weekly_budget"

    budget = replace(budget, reserved=990.0)
    assert compute(budget=budget).dropped["pct_category:fashion"] == "weekly_budget"


# --- Flat ₹ off above a minimum basket ---------------------------------------------------------


def test_flat_amount_bound_by_max_flat_amount():
    opt = option(compute(), OfferType.FLAT_ABOVE_MIN)
    assert opt.ranges["amount"] == ParamRange(MIN_FLAT_AMOUNT, 300.0)
    assert opt.binding_rules["amount"] == "max_flat_amount"
    assert opt.worst_case_cost == 300.0


@pytest.mark.parametrize(
    ("rules", "spent", "expected_hi", "expected_rule"),
    [
        (RuleSet(per_offer_cost_cap=200.0), 0.0, 200.0, "per_offer_cost_cap"),
        (RuleSet(), 49_880.0, 120.0, "weekly_budget"),
        (RuleSet(max_flat_amount=100.0, per_offer_cost_cap=150.0), 49_800.0, 100.0, "max_flat_amount"),
    ],
)
def test_flat_amount_strictest_rule_wins(rules, spent, expected_hi, expected_rule):
    opt = option(compute(rules=rules, budget=replace(NO_SPEND, spent=spent)), OfferType.FLAT_ABOVE_MIN)
    assert opt.ranges["amount"].hi == expected_hi
    assert opt.binding_rules["amount"] == expected_rule


def test_flat_min_basket_keeps_the_margin_floor_at_the_largest_amount():
    opt = option(compute(), OfferType.FLAT_ABOVE_MIN)
    room = (AVG_MARGIN - 5.0) / 100
    assert opt.ranges["min_basket"].lo == pytest.approx(300.0 / room)
    assert opt.ranges["min_basket"].hi == float("inf")
    assert opt.binding_rules["min_basket"] == "margin_floor_pct"


def test_flat_dropped_when_average_margin_is_below_the_floor():
    es = compute(rules=RuleSet(margin_floor_pct=AVG_MARGIN))
    assert (OfferType.FLAT_ABOVE_MIN, None) not in offer_types(es)
    assert es.dropped["flat_above_min"] == "margin_floor_pct"


def test_flat_dropped_when_amount_range_is_empty():
    es = compute(rules=RuleSet(max_flat_amount=MIN_FLAT_AMOUNT - 1))
    assert es.dropped["flat_above_min"] == "max_flat_amount"


# --- Free shipping, points multiplier, Nudge ---------------------------------------------------


def test_free_shipping_allowed_within_cost_cap_and_budget():
    opt = option(compute(), OfferType.FREE_SHIPPING)
    assert opt.ranges == {} and opt.worst_case_cost == 40.0
    es = compute(rules=RuleSet(per_offer_cost_cap=30.0))
    assert es.dropped["free_shipping"] == "per_offer_cost_cap"
    es = compute(budget=replace(NO_SPEND, spent=49_970.0))
    assert es.dropped["free_shipping"] == "weekly_budget"


def test_points_multiplier_bound_by_max_points_multiplier():
    opt = option(compute(), OfferType.POINTS_MULTIPLIER)
    assert opt.ranges["multiplier"] == ParamRange(MIN_POINTS_MULTIPLIER, 3.0)
    assert opt.binding_rules["multiplier"] == "max_points_multiplier"
    assert opt.worst_case_cost == pytest.approx(2.0 * AVG_BASKET * POINTS_PER_RUPEE * 0.25)


def test_points_multiplier_bound_by_cost_cap_and_budget():
    per_unit = AVG_BASKET * POINTS_PER_RUPEE * 0.25  # cost of each extra 1× of points
    opt = option(compute(rules=RuleSet(per_offer_cost_cap=50.0)), OfferType.POINTS_MULTIPLIER)
    assert opt.ranges["multiplier"].hi == pytest.approx(1 + 50.0 / per_unit)
    assert opt.binding_rules["multiplier"] == "per_offer_cost_cap"
    assert opt.worst_case_cost == pytest.approx(50.0)

    opt = option(compute(budget=replace(NO_SPEND, spent=49_950.0)), OfferType.POINTS_MULTIPLIER)
    assert opt.binding_rules["multiplier"] == "weekly_budget"

    es = compute(rules=RuleSet(per_offer_cost_cap=10.0))
    assert es.dropped["points_multiplier"] == "per_offer_cost_cap"


def test_nudge_survives_a_zero_budget():
    es = compute(budget=replace(NO_SPEND, spent=50_000.0))
    assert offer_types(es) == {(OfferType.NUDGE, None)}
    assert option(es, OfferType.NUDGE).worst_case_cost == 0.0
    assert set(es.dropped.values()) == {"weekly_budget"}
    assert set(es.dropped) == {"pct_category:fashion", "flat_above_min", "free_shipping", "points_multiplier"}


def test_overspent_budget_counts_as_zero():
    es = compute(budget=replace(NO_SPEND, spent=40_000.0, reserved=20_000.0))
    assert offer_types(es) == {(OfferType.NUDGE, None)}


# --- Send window -------------------------------------------------------------------------------


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 12, day, hour, minute)


@pytest.mark.parametrize(
    ("now", "delay", "expected"),
    [
        (at(10, 10), 24, (at(10, 10), at(10, 21))),
        (at(10, 10), 2, (at(10, 10), at(10, 12))),
        (at(10, 20, 30), 24, (at(10, 20, 30), at(10, 21))),  # clipped at the end of the day
        (at(10, 21), 24, (at(11, 9), at(11, 21))),  # 21:00 is past the last allowed hour
        (at(10, 22), 24, (at(11, 9), at(11, 21))),
        (at(10, 22), 13, (at(11, 9), at(11, 11))),
        (at(10, 22), 2, None),  # no allowed hour before the delay runs out
        (at(10, 3), 24, (at(10, 9), at(10, 21))),
        (at(10, 3), 7, (at(10, 9), at(10, 10))),
        (at(10, 3), 6, None),  # the window is half-open, so ending exactly at 09:00 leaves nothing
    ],
)
def test_send_window(now, delay, expected):
    es = compute(rules=RuleSet(max_send_delay_hours=delay), now=now)
    assert es.send_window == expected


def test_send_window_uses_send_hour_rules():
    es = compute(rules=RuleSet(send_hour_start=12, send_hour_end=14), now=at(10, 10))
    assert es.send_window == (at(10, 12), at(10, 14))


# --- Costs -------------------------------------------------------------------------------------


def test_offer_cost_per_offer_type():
    def cost(offer_type, category=None, rules=None, **params):
        return offer_cost(offer_type, category, params, CATALOG, rules or RuleSet())

    # % off: 20% of a ₹1,500 fashion basket is ₹300, under the ₹500 cap; the cap is the worst case.
    assert cost(OfferType.PCT_CATEGORY, "fashion", pct=20, cap=500) == (500, 300)
    assert cost(OfferType.PCT_CATEGORY, "fashion", pct=20, cap=200) == (200, 200)
    assert cost(OfferType.FLAT_ABOVE_MIN, amount=150, min_basket=1500) == (150, 150)
    assert cost(OfferType.FREE_SHIPPING) == (40, 40)
    assert cost(OfferType.FREE_SHIPPING, rules=RuleSet(shipping_fee=60)) == (60, 60)
    points = 1.0 * AVG_BASKET * POINTS_PER_RUPEE * 0.25
    assert cost(OfferType.POINTS_MULTIPLIER, multiplier=2) == pytest.approx((points, points))
    assert cost(OfferType.NUDGE) == (0, 0)


# --- Invariants --------------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    tier=st.sampled_from(["bronze", "silver", "gold", "platinum"]),
    cat_cap=st.floats(0, 60),
    floor=st.floats(0, 50),
    flat=st.floats(0, 1000),
    max_mult=st.floats(1, 5),
    cost_cap=st.floats(0, 1000),
    remaining=st.floats(-500, 2000),
)
def test_every_option_respects_every_bound(tier, cat_cap, floor, flat, max_mult, cost_cap, remaining):
    rules = RuleSet(
        max_pct_by_category={"fashion": cat_cap, "home": cat_cap},
        margin_floor_pct=floor,
        max_flat_amount=flat,
        max_points_multiplier=max_mult,
        per_offer_cost_cap=cost_cap,
        weekly_budget=1000.0,
    )
    budget = replace(NO_SPEND, spent=1000.0 - remaining)
    es = compute(make_state(tier=tier, categories=tuple(CATALOG.categories)), rules, budget)
    money = min(cost_cap, max(remaining, 0.0))
    assert (OfferType.NUDGE, None) in offer_types(es)
    for opt in es.options:
        for name, rng in opt.ranges.items():
            assert rng.lo <= rng.hi, (opt, name)
        assert opt.worst_case_cost <= money + 1e-9 or opt.offer_type == OfferType.NUDGE
        if opt.offer_type == OfferType.PCT_CATEGORY:
            margin = CATALOG.categories[opt.category].margin_pct
            assert opt.ranges["pct"].hi <= min(
                rules.max_pct_by_category.get(opt.category, 100.0),
                rules.max_pct_by_loyalty_tier[tier],
                margin - floor,
            )
        if opt.offer_type == OfferType.FLAT_ABOVE_MIN:
            assert opt.ranges["amount"].hi <= flat
            assert opt.ranges["amount"].hi <= opt.ranges["min_basket"].lo * (AVG_MARGIN - floor) / 100 + 1e-9
        if opt.offer_type == OfferType.POINTS_MULTIPLIER:
            assert opt.ranges["multiplier"].hi <= max_mult
    for key, rule in es.dropped.items():
        assert rule in RuleSet().to_dict(), (key, rule)


# --- CLI ---------------------------------------------------------------------------------------


def test_cli_eligible_demo(capsys):
    assert main(["eligible", "--demo"]) == 0
    out = capsys.readouterr().out
    assert "pct_category" in out and "fashion" in out
    assert "binding: max_pct_by_loyalty_tier" in out
    assert (
        "Trigger: daily sweep" in out and "nudge" in out and "dropped (binding: nudge_needs_reminder)" in out
    )
    assert "send window" in out


def test_cli_eligible_on_an_abandoned_cart_lists_the_nudge(capsys):
    assert main(["eligible", "--demo", "--trigger", "cart_abandoned"]) == 0
    out = capsys.readouterr().out
    assert "Trigger: cart abandoned" in out and "nudge_needs_reminder" not in out
    assert any(line.startswith("nudge ") and "worst ₹0" in line for line in out.splitlines())


# --- Binding Rule of an empty Eligible Set (T42) -------------------------------------------------


def test_an_empty_set_names_the_rule_that_dropped_the_most_options():
    es = compute(rules=RuleSet(weekly_budget=0.0), trigger=TriggerKind.DAILY_SWEEP)
    assert es.options == ()
    assert empty_set_binding(es) == "weekly_budget"


def test_a_set_with_an_option_left_has_no_empty_set_binding():
    assert empty_set_binding(compute(trigger=TriggerKind.DAILY_SWEEP)) is None
    assert empty_set_binding(compute(rules=RuleSet(weekly_budget=0.0))) is None  # the cart's Nudge is left
