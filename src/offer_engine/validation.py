"""Validation (ADR 0001, PLAN §3.5 step 3): re-check a chooser's Proposal against every Rule before it is sent.

Pure functions, no database. The Eligible Set is recomputed here, never taken from the chooser. Each failure is
`code: detail`, with the Rule it broke in brackets where one did, and every failure is reported, not just the first.
The result also names each check that ran (`CHECK_CODES`), so the Decision trace can mark each passed or failed.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime, timedelta

from offer_engine.domain import (
    BudgetState,
    Catalog,
    CustomerState,
    EligibleOption,
    EligibleSet,
    OfferType,
    Proposal,
    RuleSet,
    TriggerKind,
    ValidationResult,
)
from offer_engine.rules import RECENT_CATEGORY_DAYS, eligible_set, offer_cost

MAX_FEATURED = 2

# A range's lower bound comes from the engine's minimums, except where a Rule sets it.
LOWER_BOUND_RULES = {"min_basket": "margin_floor_pct"}

# Costs at the top of a range can overshoot a ₹ limit by float rounding.
COST_TOLERANCE = 1e-6

CaptionChecker = Callable[[str, Proposal, Catalog], list[str]]

# Each check `validate` may run, in order, with the failure codes it reports. The Caption Check's codes are the
# caption checker's own, so any other code belongs to it.
CHECK_CODES = {
    "short_circuit": ("short_circuit",),
    "offer_type": ("offer_type_not_eligible", "category_not_eligible"),
    "params": ("param_missing", "param_extra", "param_out_of_range"),
    "cost_cap": ("cost_over_cap",),
    "budget": ("over_budget",),
    "send_window": ("send_at_missing", "send_at_outside_window"),
    "featured": ("too_many_featured", "featured_unknown", "featured_wrong_category", "featured_not_seen"),
    "caption": ("caption_missing",),
    "reason": ("reason_missing",),
}
CAPTION_CHECK = "caption_check"


def no_caption_check(caption: str, proposal: Proposal, catalog: Catalog) -> list[str]:
    """Accepts every caption. T11 passes the real Caption Check (T08)."""
    return []


def validate(
    proposal: Proposal,
    state: CustomerState,
    rules: RuleSet,
    budget: BudgetState,
    now: datetime,
    catalog: Catalog,
    caption_checker: CaptionChecker = no_caption_check,
    trigger: TriggerKind | None = None,
) -> ValidationResult:
    """`trigger` is the Decision's Trigger: the Eligible Set it re-computes allows a Nudge only on a reminder."""
    if proposal.offer_type is None:
        return ValidationResult(ok=True)

    failures: list[str] = []
    checks = ["short_circuit"]
    es = eligible_set(state, rules, budget, now, catalog, trigger)
    if es.short_circuit is not None:
        failures.append(f"short_circuit: {es.short_circuit} ({es.binding_rule})")
    else:
        checks.append("offer_type")
        option = _match_option(proposal, es, failures)
        if option is not None:
            checks += ["params", "cost_cap", "budget"]
            failures += _param_failures(proposal.params, option)
            failures += _cost_failures(proposal, rules, budget, catalog)
        checks.append("send_window")
        failures += _send_at_failures(proposal.send_at, es, now, rules)
    checks += ["featured", "caption", "reason"]
    failures += _featured_failures(proposal, state, now, catalog)
    if not proposal.caption.strip():
        failures.append("caption_missing: empty caption")
    if not proposal.reason.strip():
        failures.append("reason_missing: empty reason")
    if proposal.caption.strip():
        checks.append(CAPTION_CHECK)
        failures += caption_checker(proposal.caption, proposal, catalog)
    return ValidationResult(ok=not failures, failures=tuple(failures), checks=tuple(checks))


def failed_check(failure: str) -> str:
    """The check a failure (`code: detail`) came from."""
    code = failure.split(":", 1)[0]
    return next((check for check, codes in CHECK_CODES.items() if code in codes), CAPTION_CHECK)


def _num(value: float) -> str:
    return f"{value:g}"


# --- Offer Type and category -------------------------------------------------------------------


def _match_option(proposal: Proposal, es: EligibleSet, failures: list[str]) -> EligibleOption | None:
    offer_type, category = proposal.offer_type, proposal.category
    for option in es.options:
        if option.offer_type == offer_type and option.category == category:
            return option

    is_pct = offer_type == OfferType.PCT_CATEGORY
    key = f"{offer_type}:{category}" if is_pct else str(offer_type)
    if key in es.dropped:
        code = "category_not_eligible" if is_pct else "offer_type_not_eligible"
        failures.append(f"{code}: {key} ({es.dropped[key]})")
    elif not any(o.offer_type == offer_type for o in es.options):
        failures.append(f"offer_type_not_eligible: {offer_type} not in the Eligible Set")
    elif is_pct:
        failures.append(f"category_not_eligible: {key} not in the Eligible Set")
    else:
        failures.append(f"category_not_eligible: {offer_type} takes no category, got {category}")
    return None


# --- Parameters and cost -----------------------------------------------------------------------


def _param_failures(params: dict[str, float], option: EligibleOption) -> list[str]:
    failures = [f"param_missing: {name}" for name in option.ranges if name not in params]
    failures += [f"param_extra: {name}" for name in params if name not in option.ranges]
    for name, r in option.ranges.items():
        if name not in params:
            continue
        value = params[name]
        if not math.isfinite(value):
            failures.append(f"param_out_of_range: {name}={_num(value)} is not a finite number")
        elif value > r.hi:
            failures.append(
                f"param_out_of_range: {name}={_num(value)} > {_num(r.hi)} ({option.binding_rules[name]})"
            )
        elif value < r.lo:
            rule = LOWER_BOUND_RULES.get(name, "minimum")
            failures.append(f"param_out_of_range: {name}={_num(value)} < {_num(r.lo)} ({rule})")
    return failures


def _cost_failures(proposal: Proposal, rules: RuleSet, budget: BudgetState, catalog: Catalog) -> list[str]:
    """Worst-case cost against the per-Offer cap and the budget left this week, whatever the budget mode."""
    try:
        cost = offer_cost(proposal.offer_type, proposal.category, proposal.params, catalog, rules)[0]
    except KeyError:  # a param is missing; already reported
        return []
    failures = []
    if cost > rules.per_offer_cost_cap + COST_TOLERANCE:
        failures.append(
            f"cost_over_cap: ₹{_num(cost)} > ₹{_num(rules.per_offer_cost_cap)} (per_offer_cost_cap)"
        )
    remaining = max(rules.weekly_budget - budget.spent - budget.reserved, 0.0)
    if cost > remaining + COST_TOLERANCE:
        failures.append(f"over_budget: ₹{_num(cost)} > ₹{_num(remaining)} left (weekly_budget)")
    return failures


# --- Send time ---------------------------------------------------------------------------------


def _send_at_failures(send_at: datetime | None, es: EligibleSet, now: datetime, rules: RuleSet) -> list[str]:
    if send_at is None:
        return ["send_at_missing: no send time"]
    window = es.send_window
    if window is None:
        return [
            f"send_at_outside_window: no send window before {_time(now + _delay(rules))} (max_send_delay_hours)"
        ]
    start, end = window
    if start <= send_at < end:
        return []
    return [
        f"send_at_outside_window: {_time(send_at)} not in [{_time(start)}, {_time(end)}) ({_send_rule(send_at, now, rules)})"
    ]


def _send_rule(send_at: datetime, now: datetime, rules: RuleSet) -> str:
    """The Rule a send time outside the window breaks. `send_window` means a later day's allowed hours: only the
    first allowed span is open.
    """
    if send_at < now:
        return "in the past"
    if send_at >= now + _delay(rules):
        return "max_send_delay_hours"
    if send_at.hour < rules.send_hour_start:
        return "send_hour_start"
    midnight = send_at.replace(hour=0, minute=0, second=0, microsecond=0)
    if send_at >= midnight + timedelta(hours=rules.send_hour_end):
        return "send_hour_end"
    return "send_window"


def _delay(rules: RuleSet) -> timedelta:
    return timedelta(hours=rules.max_send_delay_hours)


def _time(at: datetime) -> str:
    return at.strftime("%Y-%m-%d %H:%M")


# --- Featured products -------------------------------------------------------------------------


def _featured_failures(
    proposal: Proposal, state: CustomerState, now: datetime, catalog: Catalog
) -> list[str]:
    """Featured products must be real, in the chosen category (if any) and in the Customer's own events of the
    last 90 days.
    """
    featured = proposal.featured_product_ids
    failures = []
    if len(featured) > MAX_FEATURED:
        failures.append(f"too_many_featured: {len(featured)} > {MAX_FEATURED}")
    since = now - timedelta(days=RECENT_CATEGORY_DAYS)
    seen = {
        e.product_id
        for e in state.events
        if e.customer_id == state.customer.id and e.product_id and since <= e.at <= now
    }
    for product_id in featured:
        product = catalog.products.get(product_id)
        if product is None:
            failures.append(f"featured_unknown: {product_id}")
            continue
        if proposal.category is not None and product.category != proposal.category:
            failures.append(
                f"featured_wrong_category: {product_id} is {product.category}, not {proposal.category}"
            )
        if product_id not in seen:
            failures.append(
                f"featured_not_seen: {product_id} not in the Customer's events of the last {RECENT_CATEGORY_DAYS} days"
            )
    return failures
