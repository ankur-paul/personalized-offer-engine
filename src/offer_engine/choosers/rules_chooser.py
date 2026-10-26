"""The rules chooser (PLAN "Assumed › Deciding"): the Fallback, the chooser for Customers without a chat, and the
Rules Only Policy.

It tries a grid of parameters in every option and picks the one maximising Lift × expected margin − expected cost,
or No Offer if nothing is positive. Ties keep the option listed first, then the smaller parameters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from offer_engine.choosers.priors import BASE_BUY_CHANCE, lift_at, offer_depth
from offer_engine.domain import (
    Catalog,
    CustomerState,
    EligibleOption,
    EligibleSet,
    OfferType,
    Proposal,
    RuleSet,
)
from offer_engine.rules import RECENT_CATEGORY_DAYS, offer_cost
from offer_engine.validation import MAX_FEATURED

FLAT_STEP = 50.0
MIN_BASKET_STEP = 50.0
CAP_STEP = 10.0
MULTIPLIER_STEP = 0.5

CART_KINDS = ("add_to_cart", "cart_abandoned")
VIEW_KINDS = ("product_view",)

# Captions carry no numbers: the Offer Card shows the terms (ADR 0005).
CAPTIONS = {
    OfferType.PCT_CATEGORY: "Still thinking about {product}? Here's something to help.",
    OfferType.FLAT_ABOVE_MIN: "Still thinking about {product}? Here's a little off your next order.",
    OfferType.FREE_SHIPPING: "Still thinking about {product}? Delivery is on us this time.",
    OfferType.POINTS_MULTIPLIER: "Still thinking about {product}? Your next order earns extra points.",
    OfferType.NUDGE: "Still thinking about {product}? It's still here when you're ready.",
}
PRODUCT_FALLBACK = "your {category} picks"
NO_PRODUCT = "your next order"


@dataclass(frozen=True)
class Assessment:
    """The rules chooser's view of one option at one set of parameters, in ₹ and chances."""

    lift: float
    redeem_chance: float
    margin: float  # expected margin of the order the Offer is for
    cost_if_redeemed: float
    value: float

    @property
    def expected_cost(self) -> float:
        return self.redeem_chance * self.cost_if_redeemed


def choose(eligible: EligibleSet, state: CustomerState, catalog: Catalog, rules: RuleSet) -> Proposal:
    if eligible.short_circuit is not None:
        return Proposal(None, reason=f"No Offer: {eligible.short_circuit} ({eligible.binding_rule})")
    if eligible.send_window is None:
        return Proposal(None, reason="No Offer: no send time left (max_send_delay_hours)")
    if not eligible.options:
        return Proposal(None, reason="No Offer: the Rules leave no option")

    focus = focus_category(state, eligible.at, catalog)
    best: tuple[EligibleOption, dict[str, float], Assessment] | None = None
    for option in eligible.options:
        for params in candidate_params(option, catalog, focus):
            a = assess(option, params, catalog, rules, focus)
            if best is None or a.value > best[2].value:
                best = (option, params, a)
    if best is None or best[2].value <= 0:
        detail = f"; best was {_describe(best[0], best[2])}" if best else ""
        return Proposal(None, reason=f"No Offer: no option has positive expected value{detail}")

    option, params, a = best
    featured = featured_products(state, eligible.at, catalog, option.category or focus)
    return Proposal(
        offer_type=option.offer_type,
        category=option.category,
        params=params,
        featured_product_ids=featured,
        send_at=eligible.send_window[0],
        caption=caption(option.offer_type, featured, option.category or focus, catalog),
        reason=f"highest expected value: {_describe(option, a)}",
    )


def assess(
    option: EligibleOption, params: dict[str, float], catalog: Catalog, rules: RuleSet, focus: str | None
) -> Assessment:
    """Value = Lift × expected margin − Redemption chance × cost if redeemed. A category option is valued on its
    own category; the others on the Customer's focus category, else the catalog average.
    """
    category = option.category or focus
    cats = (
        [catalog.categories[category]]
        if category in catalog.categories
        else list(catalog.categories.values())
    )
    basket = sum(c.avg_basket for c in cats) / len(cats) if cats else 0.0
    margin = sum(c.avg_basket * c.margin_pct / 100 for c in cats) / len(cats) if cats else 0.0
    lift = lift_at(option.offer_type, offer_depth(option.offer_type, params, basket), option.estimated_lift)
    chance = min(max(BASE_BUY_CHANCE + lift, 0.0), 1.0)
    cost = offer_cost(option.offer_type, option.category, params, catalog, rules)[1]
    return Assessment(lift, chance, margin, cost, lift * margin - chance * cost)


def candidate_params(option: EligibleOption, catalog: Catalog, focus: str | None) -> list[dict[str, float]]:
    """Every parameter set the chooser tries, each inside the option's ranges."""
    r = option.ranges
    if option.offer_type == OfferType.PCT_CATEGORY:
        basket = catalog.categories[option.category].avg_basket
        out = []
        for pct in _grid(r["pct"].lo, r["pct"].hi, 1.0):
            # The cap matches the expected discount, so the worst case is no worse than expected.
            cap = _clamp(math.ceil(pct * basket / 100 / CAP_STEP) * CAP_STEP, r["cap"].lo, r["cap"].hi)
            out.append({"pct": pct, "cap": cap})
        return out
    if option.offer_type == OfferType.FLAT_ABOVE_MIN:
        min_basket = math.ceil(r["min_basket"].lo / MIN_BASKET_STEP) * MIN_BASKET_STEP
        return [
            {"amount": a, "min_basket": min_basket} for a in _grid(r["amount"].lo, r["amount"].hi, FLAT_STEP)
        ]
    if option.offer_type == OfferType.POINTS_MULTIPLIER:
        return [{"multiplier": m} for m in _grid(r["multiplier"].lo, r["multiplier"].hi, MULTIPLIER_STEP)]
    return [{}]


def focus_category(state: CustomerState, now: datetime, catalog: Catalog) -> str | None:
    """The category of the Customer's latest cart, else latest view, within the last 90 days."""
    for kinds in (CART_KINDS, VIEW_KINDS):
        recent = _recent(state, now, kinds, None, catalog)
        if recent:
            return recent[0].category
    return None


def featured_products(
    state: CustomerState, now: datetime, catalog: Catalog, category: str | None
) -> tuple[str, ...]:
    """Up to 2 products in `category` the Customer carted (first) or viewed in the last 90 days, newest first."""
    if category is None:
        return ()
    ids: list[str] = []
    for kinds in (CART_KINDS, VIEW_KINDS):
        for event in _recent(state, now, kinds, category, catalog):
            if event.product_id in catalog.products and event.product_id not in ids:
                ids.append(event.product_id)
    return tuple(ids[:MAX_FEATURED])


def caption(offer_type: OfferType, featured: tuple[str, ...], category: str | None, catalog: Catalog) -> str:
    if featured:
        product = short_name(catalog.products[featured[0]].name)
    elif category:
        product = PRODUCT_FALLBACK.format(category=category)
    else:
        product = NO_PRODUCT
    return CAPTIONS[offer_type].format(product=product)


def short_name(name: str) -> str:
    """The product name without words holding digits ("Basmati Rice 5kg" → "Basmati Rice")."""
    words = [w for w in name.split() if not any(ch.isdigit() for ch in w)]
    return " ".join(words) or "it"


def _recent(
    state: CustomerState, now: datetime, kinds: tuple[str, ...], category: str | None, catalog: Catalog
):
    since = now - timedelta(days=RECENT_CATEGORY_DAYS)
    events = [
        e
        for e in state.events
        if e.kind in kinds
        and since <= e.at <= now
        and e.category in catalog.categories
        and (category is None or e.category == category)
    ]
    return sorted(events, key=lambda e: e.at, reverse=True)


def _grid(lo: float, hi: float, step: float) -> list[float]:
    """Multiples of `step` in [lo, hi], or [lo] if there are none."""
    first = math.ceil(lo / step - 1e-9)
    last = math.floor(hi / step + 1e-9)
    values = [n * step for n in range(first, last + 1) if lo <= n * step <= hi]
    return values or [lo]


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(max(value, lo), hi)


def _describe(option: EligibleOption, a: Assessment) -> str:
    name = f"{option.offer_type} {option.category}" if option.category else str(option.offer_type)
    source = "prior" if option.estimated_lift is None else "estimated"
    return (
        f"{name}: Lift {a.lift:.1%} ({source}) × ₹{a.margin:,.0f} margin − {a.redeem_chance:.0%} × "
        f"₹{a.cost_if_redeemed:,.0f} cost = ₹{a.value:,.1f}"
    )
