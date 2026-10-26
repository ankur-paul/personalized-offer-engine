"""The Rules engine (ADR 0001, PLAN §3.3, §3.5 step 1): the Eligible Set for one Customer at one moment.

Pure functions, no database. Strictest wins: every upper bound is the min over the Rules that bound it, and the
Rule that gave the min is recorded as the Binding Rule. A bound that ties keeps the Rule listed first.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime, timedelta

from offer_engine.domain import (
    BudgetState,
    Catalog,
    CustomerState,
    EligibleOption,
    EligibleSet,
    OfferStatus,
    OfferType,
    ParamRange,
    RuleSet,
    TriggerKind,
)

# Lower bounds that no Rule sets: smaller Offers aren't worth sending.
MIN_PCT = 5.0
MIN_CAP = 50.0
MIN_FLAT_AMOUNT = 50.0
MIN_POINTS_MULTIPLIER = 1.5

# The marketplace earn rate: 1 point per ₹10. Must match the generator's (sim/generate/history.py).
POINTS_PER_RUPEE = 0.1

RECENT_CATEGORY_DAYS = 90

# A Nudge reminds the Customer of something, so only these Triggers allow one (GLOSSARY, QnA Q56). Elsewhere it
# is dropped with this name as its Binding Rule.
NUDGE_TRIGGERS = frozenset({TriggerKind.CART_ABANDONED, TriggerKind.POINTS_EXPIRING})
NUDGE_NEEDS_REMINDER = "nudge_needs_reminder"

_TESTER_SUFFIX = re.compile(r"-t\d+$")

Bound = tuple[str, float]


def in_holdout(customer_id: str, holdout_pct: float) -> bool:
    """Hash-based and permanent; a Tester copy (`<id>-t<telegram id>`) shares its source's Holdout."""
    source_id = _TESTER_SUFFIX.sub("", customer_id)
    digest = hashlib.sha256(source_id.encode()).digest()
    return int.from_bytes(digest[:8], "big") % 10_000 < holdout_pct * 100


def fatigue_paused_until(state: CustomerState, rules: RuleSet) -> datetime | None:
    """End of the latest Fatigue Pause: `fatigue_dismissals` dismissals within `fatigue_window_days` pause
    Offers for `fatigue_pause_days` from the last of them. May be in the past; None if never paused.

    A PastOffer has no dismissal time, so its `created_at` stands in for it.
    """
    n = rules.fatigue_dismissals
    if n < 1:
        return None
    times = sorted(o.created_at for o in state.offers if o.status == OfferStatus.DISMISSED)
    window = timedelta(days=rules.fatigue_window_days)
    until = None
    for i in range(n - 1, len(times)):
        if times[i] - times[i - n + 1] <= window:
            until = times[i] + timedelta(days=rules.fatigue_pause_days)
    return until


def offer_cost(
    offer_type: OfferType, category: str | None, params: dict[str, float], catalog: Catalog, rules: RuleSet
) -> tuple[float, float]:
    """(worst case, expected if redeemed) in ₹, per the cost model in PLAN "Assumed › Deciding".

    The caller multiplies the expected cost by the Redemption chance.
    """
    if offer_type == OfferType.PCT_CATEGORY:
        basket = catalog.categories[category].avg_basket
        cap = float(params["cap"])
        return cap, min(params["pct"] * basket / 100, cap)
    if offer_type == OfferType.FLAT_ABOVE_MIN:
        return float(params["amount"]), float(params["amount"])
    if offer_type == OfferType.FREE_SHIPPING:
        return rules.shipping_fee, rules.shipping_fee
    if offer_type == OfferType.POINTS_MULTIPLIER:
        cost = (params["multiplier"] - 1) * _points_cost_per_multiple(category, catalog, rules)
        return cost, cost
    return 0.0, 0.0


def eligible_set(
    state: CustomerState,
    rules: RuleSet,
    budget: BudgetState,
    now: datetime,
    catalog: Catalog,
    trigger: TriggerKind | None = None,
) -> EligibleSet:
    """`trigger` decides whether a Nudge is eligible; without one there is nothing to remind about, so no Nudge."""
    customer = state.customer
    stop = _short_circuit(state, rules, now)
    if stop is not None:
        name, rule = stop
        return EligibleSet(customer.id, now, (), None, short_circuit=name, binding_rule=rule)

    remaining = max(rules.weekly_budget - budget.spent - budget.reserved, 0.0)
    money: list[Bound] = [("per_offer_cost_cap", rules.per_offer_cost_cap), ("weekly_budget", remaining)]
    options: list[EligibleOption] = []
    dropped: dict[str, str] = {}

    for category in _recent_categories(state, now, catalog):
        _add(options, dropped, _pct_category(category, customer.loyalty_tier, money, catalog, rules))
    _add(options, dropped, _flat_above_min(money, catalog, rules))
    _add(options, dropped, _free_shipping(money, rules))
    _add(options, dropped, _points_multiplier(money, catalog, rules))
    if trigger in NUDGE_TRIGGERS:
        options.append(EligibleOption(OfferType.NUDGE, None, {}, {}, worst_case_cost=0.0))
    else:
        dropped[str(OfferType.NUDGE)] = NUDGE_NEEDS_REMINDER

    return EligibleSet(customer.id, now, tuple(options), _send_window(now, rules), dropped=dropped)


def empty_set_binding(es: EligibleSet) -> str | None:
    """The Binding Rule of a No Offer that the Rules forced by dropping every option, e.g. `weekly_budget` once
    the budget is spent: the Rule that dropped the most options, the first listed on a tie. None when an option is
    left, since then the chooser chose No Offer. The Nudge's `nudge_needs_reminder` counts only when nothing else
    dropped an option."""
    if es.options or not es.dropped:
        return None
    reasons = [r for r in es.dropped.values() if r != NUDGE_NEEDS_REMINDER] or list(es.dropped.values())
    return Counter(reasons).most_common(1)[0][0]


# --- Short-circuits ----------------------------------------------------------------------------


def _short_circuit(state: CustomerState, rules: RuleSet, now: datetime) -> tuple[str, str] | None:
    """The first check that stops all Offers, as (short_circuit, Binding Rule)."""
    customer = state.customer
    if customer.opted_out:
        return "opt_out", "opt_out"
    if in_holdout(customer.id, rules.holdout_pct):
        return "holdout", "holdout_pct"
    paused_until = fatigue_paused_until(state, rules)
    if paused_until is not None and now < paused_until:
        return "fatigue_pause", "fatigue_dismissals"
    since = now - timedelta(days=rules.frequency_cap_days)
    recent = sum(1 for o in state.offers if since < o.created_at <= now)
    if recent >= rules.frequency_cap_count:
        return "frequency_cap", "frequency_cap_count"
    since = now - timedelta(days=rules.cooldown_days_after_redemption)
    if any(o.redeemed_at is not None and since < o.redeemed_at <= now for o in state.offers):
        return "cooldown", "cooldown_days_after_redemption"
    if now - customer.signup_at < timedelta(days=rules.min_days_since_signup):
        return "eligibility", "min_days_since_signup"
    return None


# --- Options -----------------------------------------------------------------------------------

# An option builder returns the option, or (dropped key, Binding Rule) when a range is empty.
Built = EligibleOption | tuple[str, str]


def _add(options: list[EligibleOption], dropped: dict[str, str], built: Built) -> None:
    if isinstance(built, EligibleOption):
        options.append(built)
    else:
        dropped[built[0]] = built[1]


def _strictest(bounds: list[Bound]) -> Bound:
    best = bounds[0]
    for bound in bounds[1:]:
        if bound[1] < best[1]:
            best = bound
    return best


def _recent_categories(state: CustomerState, now: datetime, catalog: Catalog) -> list[str]:
    since = now - timedelta(days=RECENT_CATEGORY_DAYS)
    return sorted(
        {e.category for e in state.events if e.category in catalog.categories and since <= e.at <= now}
    )


def _pct_category(category: str, tier: str, money: list[Bound], catalog: Catalog, rules: RuleSet) -> Built:
    key = f"{OfferType.PCT_CATEGORY}:{category}"
    pct_bounds: list[Bound] = []
    if category in rules.max_pct_by_category:
        pct_bounds.append(("max_pct_by_category", rules.max_pct_by_category[category]))
    if tier in rules.max_pct_by_loyalty_tier:
        pct_bounds.append(("max_pct_by_loyalty_tier", rules.max_pct_by_loyalty_tier[tier]))
    pct_bounds.append(("margin_floor_pct", catalog.categories[category].margin_pct - rules.margin_floor_pct))
    pct_rule, pct_hi = _strictest(pct_bounds)
    if pct_hi < MIN_PCT:
        return key, pct_rule
    cap_rule, cap_hi = _strictest(money)
    if cap_hi < MIN_CAP:
        return key, cap_rule
    params = {"pct": pct_hi, "cap": cap_hi}
    return EligibleOption(
        OfferType.PCT_CATEGORY,
        category,
        {"pct": ParamRange(MIN_PCT, pct_hi), "cap": ParamRange(MIN_CAP, cap_hi)},
        {"pct": pct_rule, "cap": cap_rule},
        worst_case_cost=offer_cost(OfferType.PCT_CATEGORY, category, params, catalog, rules)[0],
    )


def _flat_above_min(money: list[Bound], catalog: Catalog, rules: RuleSet) -> Built:
    """`min_basket` is set at the largest allowed amount, so the margin floor holds for any amount in range."""
    key = str(OfferType.FLAT_ABOVE_MIN)
    room = _avg_margin(catalog) - rules.margin_floor_pct
    if room <= 0:
        return key, "margin_floor_pct"
    amount_rule, amount_hi = _strictest([("max_flat_amount", rules.max_flat_amount), *money])
    if amount_hi < MIN_FLAT_AMOUNT:
        return key, amount_rule
    min_basket = amount_hi / (room / 100)
    return EligibleOption(
        OfferType.FLAT_ABOVE_MIN,
        None,
        {
            "amount": ParamRange(MIN_FLAT_AMOUNT, amount_hi),
            "min_basket": ParamRange(min_basket, float("inf")),
        },
        {"amount": amount_rule, "min_basket": "margin_floor_pct"},
        worst_case_cost=amount_hi,
    )


def _free_shipping(money: list[Bound], rules: RuleSet) -> Built:
    for rule, limit in money:
        if rules.shipping_fee > limit:
            return str(OfferType.FREE_SHIPPING), rule
    return EligibleOption(OfferType.FREE_SHIPPING, None, {}, {}, worst_case_cost=rules.shipping_fee)


def _points_multiplier(money: list[Bound], catalog: Catalog, rules: RuleSet) -> Built:
    per_multiple = _points_cost_per_multiple(None, catalog, rules)
    bounds: list[Bound] = [("max_points_multiplier", rules.max_points_multiplier)]
    if per_multiple > 0:
        bounds += [(rule, 1 + limit / per_multiple) for rule, limit in money]
    rule, hi = _strictest(bounds)
    if hi < MIN_POINTS_MULTIPLIER:
        return str(OfferType.POINTS_MULTIPLIER), rule
    return EligibleOption(
        OfferType.POINTS_MULTIPLIER,
        None,
        {"multiplier": ParamRange(MIN_POINTS_MULTIPLIER, hi)},
        {"multiplier": rule},
        worst_case_cost=(hi - 1) * per_multiple,
    )


def _points_cost_per_multiple(category: str | None, catalog: Catalog, rules: RuleSet) -> float:
    """₹ cost of each extra 1× of points on an expected basket (the category's, else the catalog average)."""
    basket = catalog.categories[category].avg_basket if category else _avg_basket(catalog)
    return basket * POINTS_PER_RUPEE * rules.point_value


def _avg_margin(catalog: Catalog) -> float:
    cats = catalog.categories.values()
    return sum(c.margin_pct for c in cats) / len(cats) if cats else 0.0


def _avg_basket(catalog: Catalog) -> float:
    cats = catalog.categories.values()
    return sum(c.avg_basket for c in cats) / len(cats) if cats else 0.0


# --- Send window -------------------------------------------------------------------------------


def _send_window(now: datetime, rules: RuleSet) -> tuple[datetime, datetime] | None:
    """The first allowed span at or after `now`, as half-open [start, end): inside the send hours and no later
    than `now + max_send_delay_hours`. None if no allowed moment is left before the delay runs out.
    """
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = midnight + timedelta(hours=rules.send_hour_start)
    end = midnight + timedelta(hours=rules.send_hour_end)
    if start >= end:
        return None
    if now >= end:
        start, end = start + timedelta(days=1), end + timedelta(days=1)
    window_start = max(now, start)
    window_end = min(end, now + timedelta(hours=rules.max_send_delay_hours))
    return (window_start, window_end) if window_start < window_end else None
