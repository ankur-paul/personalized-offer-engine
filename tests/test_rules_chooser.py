"""The rules chooser (T09, PLAN "Assumed › Deciding"): highest Lift × margin − expected cost, or No Offer."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from offer_engine import caption_check
from offer_engine.choosers import rules_chooser
from offer_engine.choosers.priors import lift_at, offer_depth
from offer_engine.domain import (
    LOYALTY_TIERS,
    BudgetState,
    Catalog,
    Category,
    Customer,
    CustomerState,
    Event,
    OfferType,
    Product,
    RuleSet,
    TriggerKind,
)
from offer_engine.rules import RECENT_CATEGORY_DAYS, eligible_set, in_holdout
from offer_engine.validation import validate

NOW = datetime(2026, 12, 10, 10, 0)
MARGINS = {"electronics": 10.0, "fashion": 45.0, "grocery": 15.0, "beauty": 40.0, "home": 30.0}
BASKETS = {"electronics": 7500.0, "fashion": 1400.0, "grocery": 650.0, "beauty": 850.0, "home": 1800.0}
# Names with sizes and model numbers, as the generator writes them.
NAMES = ["Basmati Rice 5kg", "Kurta Set (2 pcs)", "Phone X12 128GB", "Face Serum 30ml"]
CATALOG = Catalog(
    categories={c: Category(c, MARGINS[c], BASKETS[c]) for c in MARGINS},
    products={
        f"{c}-{i}": Product(f"{c}-{i}", f"{c.title()} {name}", c, 100.0 * (i + 1))
        for c in MARGINS
        for i, name in enumerate(NAMES)
    },
)
NO_SPEND = BudgetState(NOW - timedelta(days=3), spent=0.0, reserved=0.0)
OUT_IDS = [f"C{n:05d}" for n in range(1, 200) if not in_holdout(f"C{n:05d}", 10.0)]
IN_ID = next(f"C{n:05d}" for n in range(1, 10_000) if in_holdout(f"C{n:05d}", 10.0))


def state_with(*events: tuple[float, str, str], customer_id: str = OUT_IDS[0], tier: str = "silver"):
    """Events as (days ago, kind, product id)."""
    customer = Customer(customer_id, NOW - timedelta(days=300), 1, "android", "organic", tier, 0, None)
    evs = tuple(
        Event(customer_id, NOW - timedelta(days=d), kind, CATALOG.products[p].category, p)
        for d, kind, p in events
    )
    return CustomerState(customer=customer, events=evs, offers=())


def choose(state, rules=None, budget=NO_SPEND, now=NOW, estimate=None, trigger=TriggerKind.CART_ABANDONED):
    """An abandoned cart by default, as the states below cart a product, so the Nudge is an option (QnA Q56)."""
    rules = rules or RuleSet()
    es = eligible_set(state, rules, budget, now, CATALOG, trigger)
    if estimate is not None:
        es = replace(es, options=tuple(replace(o, estimated_lift=estimate(o)) for o in es.options))
    return es, rules_chooser.choose(es, state, CATALOG, rules)


def test_fashion_cart_gets_a_fashion_discount_inside_its_range():
    state = state_with((2, "product_view", "fashion-1"), (1, "add_to_cart", "fashion-0"))
    es, p = choose(state)
    assert p.offer_type == OfferType.PCT_CATEGORY and p.category == "fashion"
    option = next(o for o in es.options if o.category == "fashion")
    for name, value in p.params.items():
        assert option.ranges[name].lo <= value <= option.ranges[name].hi
    assert validate(p, state, RuleSet(), NO_SPEND, NOW, CATALOG, trigger=TriggerKind.CART_ABANDONED).ok


def test_picks_the_depth_with_the_highest_value_not_the_deepest():
    state = state_with((1, "add_to_cart", "fashion-0"))
    rules = RuleSet(max_pct_by_loyalty_tier={t: 40.0 for t in LOYALTY_TIERS})
    _, p = choose(state, rules)
    assert 5 < p.params["pct"] < 40


def test_no_offer_when_every_option_has_non_positive_value():
    state = state_with((1, "add_to_cart", "fashion-0"), (3, "product_view", "grocery-1"))
    for lift in (0.0, -0.05):
        _, p = choose(state, estimate=lambda o, lift=lift: lift)
        assert p.offer_type is None
        assert "no option has positive expected value" in p.reason


def test_estimated_lift_changes_the_pick():
    state = state_with((1, "add_to_cart", "fashion-0"))
    _, p = choose(state, estimate=lambda o: 0.2 if o.offer_type == OfferType.NUDGE else 0.0)
    assert p.offer_type == OfferType.NUDGE


def test_short_circuit_is_no_offer():
    _, p = choose(state_with((1, "add_to_cart", "fashion-0"), customer_id=IN_ID))
    assert p.offer_type is None and "holdout" in p.reason


def test_no_send_window_is_no_offer():
    rules = RuleSet(send_hour_start=9, send_hour_end=10, max_send_delay_hours=1)
    _, p = choose(state_with((1, "add_to_cart", "fashion-0")), rules, now=NOW.replace(hour=11))
    assert p.offer_type is None and "max_send_delay_hours" in p.reason


def test_featured_products_carted_first_then_viewed_in_the_chosen_category():
    state = state_with(
        (1, "product_view", "fashion-3"),
        (2, "add_to_cart", "fashion-1"),
        (3, "product_view", "grocery-0"),
        (5, "add_to_cart", "fashion-2"),
        (RECENT_CATEGORY_DAYS + 5, "add_to_cart", "fashion-0"),
    )
    assert rules_chooser.featured_products(state, NOW, CATALOG, "fashion") == ("fashion-1", "fashion-2")
    assert rules_chooser.featured_products(state, NOW, CATALOG, None) == ()


def test_send_at_is_the_start_of_the_send_window():
    es, p = choose(state_with((1, "add_to_cart", "fashion-0")), now=NOW.replace(hour=6))
    assert p.send_at == es.send_window[0] == NOW.replace(hour=9)


def test_short_name_drops_words_with_digits():
    assert rules_chooser.short_name("Annapurna Basmati Rice 5kg") == "Annapurna Basmati Rice"
    assert rules_chooser.short_name("X12 128GB") == "it"


def test_lift_prior_saturates():
    lifts = [
        lift_at(OfferType.PCT_CATEGORY, offer_depth(OfferType.PCT_CATEGORY, {"pct": d}, 1000))
        for d in (5, 15, 50)
    ]
    assert lifts[0] < lifts[1] < lifts[2] and lifts[2] - lifts[1] < lifts[1] - lifts[0]


# --- Property: every proposal passes Validation and the Caption Check, with no digits in the caption ----------


@st.composite
def cases(draw):
    now = NOW.replace(hour=draw(st.integers(0, 23)))
    start = draw(st.integers(0, 20))
    rules = RuleSet(
        max_pct_by_loyalty_tier={t: draw(st.floats(0, 40)) for t in LOYALTY_TIERS},
        margin_floor_pct=draw(st.floats(0, 20)),
        max_flat_amount=draw(st.floats(0, 600)),
        max_points_multiplier=draw(st.floats(1, 5)),
        per_offer_cost_cap=draw(st.floats(20, 1000)),
        send_hour_start=start,
        send_hour_end=draw(st.integers(start + 1, 24)),
        max_send_delay_hours=draw(st.integers(1, 48)),
    )
    events = draw(
        st.lists(
            st.tuples(
                st.floats(0, 120),
                st.sampled_from(["product_view", "add_to_cart", "cart_abandoned", "order"]),
                st.sampled_from(sorted(CATALOG.products)),
            ),
            max_size=8,
        )
    )
    state = state_with(
        *events, customer_id=draw(st.sampled_from(OUT_IDS)), tier=draw(st.sampled_from(LOYALTY_TIERS))
    )
    budget = BudgetState(NOW - timedelta(days=3), spent=draw(st.floats(0, 50_000)), reserved=0.0)
    lift = draw(st.none() | st.floats(-0.1, 0.3))
    return state, rules, budget, now, lift


@given(cases())
@settings(max_examples=300, deadline=None)
def test_proposals_always_pass_validation_and_the_caption_check(case):
    state, rules, budget, now, lift = case
    _, p = choose(state, rules, budget, now, estimate=lambda o: lift)
    assert validate(p, state, rules, budget, now, CATALOG, trigger=TriggerKind.CART_ABANDONED).ok
    if p.offer_type is not None:
        assert not re.search(r"\d", p.caption)
        assert caption_check.check(p.caption, p, CATALOG, validity_days=rules.offer_validity_days) == []
