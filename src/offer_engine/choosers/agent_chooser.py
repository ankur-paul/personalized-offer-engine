"""The agent chooser (ADR 0001, 0005; PLAN §3.5 step 2): Claude picks one option from the Eligible Set or No Offer,
sets its parameters and featured products, and writes the caption and a short reason.

One Messages API call with one tool, `propose_offer`. Any API error, refusal or unusable answer raises, so the
pipeline falls back to the rules chooser. The agent sees only observable data, never Ground Truth (ADR 0002).
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from offer_engine.choosers.priors import PRIORS
from offer_engine.domain import (
    Catalog,
    CustomerState,
    EligibleSet,
    OfferType,
    Proposal,
    RuleSet,
    TriggerKind,
)
from offer_engine.rules import RECENT_CATEGORY_DAYS

TOOL_NAME = "propose_offer"
TIMEOUT_SECONDS = 20.0
MAX_TOKENS = 8000
EFFORT = "low"
MAX_REASON = 200
NO_OFFER_INDEX = -1

# How much history the prompt shows; the counts cover everything in the last 90 days.
MAX_RECENT_EVENTS = 20
MAX_SEEN_PRODUCTS = 12
QUIET_KINDS = ("session", "product_view")

PARAM_NAMES = ("pct", "cap", "amount", "min_basket", "multiplier")
PARAM_UNITS = {"pct": "%", "cap": "₹", "amount": "₹", "min_basket": "₹", "multiplier": "×"}

TRIGGERS = {
    TriggerKind.CART_ABANDONED: "left a cart without buying",
    TriggerKind.POINTS_EXPIRING: "has loyalty points expiring soon",
    TriggerKind.LONG_GAP: "hasn't ordered for a long time",
    TriggerKind.FIRST_ORDER_DELIVERED: "just received their first order",
    TriggerKind.DAILY_SWEEP: "is up for the daily win-back and lapse check",
    TriggerKind.ON_REQUEST: "asked for Offers with /offers",
}

SYSTEM_PROMPT = """\
You decide which Offer, if any, a Customer of an Indian online marketplace gets right now, and you write the \
caption that goes with it on Telegram.

## The goal: Incremental Margin
A discount sent to someone who would have bought anyway is lost margin. Maximise the margin the Offer adds: \
Lift (the extra chance this Customer buys because of the Offer) × the margin of that order, minus the expected \
cost of the Offer. Prefer the cheapest Offer that captures most of the Lift. A Nudge (a reminder with no \
incentive, zero cost) is often enough for a Customer who is already keen. No Offer is a good answer when \
nothing is likely to pay for itself.

## What you may choose
The Rules have already computed the Eligible Set: the Offer Types, categories and parameter ranges this \
Customer may get. Pick exactly one option by its index, or -1 for No Offer. Every parameter must lie inside its \
range, inclusive. The Binding Rule named next to a range is the Rule that set its limit.

Parameters by Offer Type (send exactly these; set the others to null):
- pct_category: `pct` (% off the category) and `cap` (the most it can take off, ₹).
- flat_above_min: `amount` (₹ off) and `min_basket` (the order must be at least this, ₹).
- points_multiplier: `multiplier` (× the usual loyalty points on the next order).
- free_shipping and nudge: no parameters.

Featured products: up to 2 product IDs from the Customer's own recent products listed in the message, in the \
chosen Offer's category when it has one. An empty list is fine.

## The caption
The Offer Card shows the terms (amount, cap, minimum basket, category, expiry), drawn by code. Your caption is \
the friendly line above it. The caption:
- contains no numbers at all: no digits, number words, prices, percentages, multipliers or ₹ amounts;
- names no deadline or time: no "tonight", "today only", "this weekend", weekdays, dates, hours or "kal tak";
- invents no urgency or scarcity: no "hurry", "last chance", "only a few left", "selling fast";
- promises nothing the Offer doesn't give: no free gifts, cashback or extra discounts, and no free delivery \
unless the Offer is free_shipping;
- is at most 280 characters, warm and plain, may name the featured product or category, and may use a little \
Hinglish.

## The reason
One sentence of at most 200 characters for the marketing team: why this option and these parameters, or why \
No Offer.

Answer by calling the propose_offer tool exactly once.
"""

TOOL = {
    "name": TOOL_NAME,
    "description": (
        "Propose one option from the Eligible Set (by index) or No Offer (-1), with its parameters, up to 2 "
        "featured product IDs, the caption and the reason."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "option_index": {
                "type": "integer",
                "description": "Index of the chosen Eligible Set option, or -1 for No Offer.",
            },
            "params": {
                "type": "object",
                "description": "The chosen option's parameters; null for every parameter it doesn't take.",
                "properties": {
                    name: {"anyOf": [{"type": "number"}, {"type": "null"}]} for name in PARAM_NAMES
                },
                "required": list(PARAM_NAMES),
                "additionalProperties": False,
            },
            "featured_product_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Up to 2 product IDs from the Customer's recent products.",
            },
            "caption": {"type": "string", "description": "At most 280 characters; no numbers or deadlines."},
            "reason": {"type": "string", "description": "At most 200 characters."},
        },
        "required": ["option_index", "params", "featured_product_ids", "caption", "reason"],
        "additionalProperties": False,
    },
}


class AgentError(RuntimeError):
    """The agent's answer can't be turned into a Proposal."""


class AgentChooser:
    """A chooser (`pipeline.ChooserFn`). `last_output` is the raw tool input of the latest call, for the Decision
    log; None if no tool input came back.
    """

    def __init__(self, client: Any, model: str, trigger: TriggerKind | None = None):
        self.client = client
        self.model = model
        self.trigger = trigger
        self.last_output: dict[str, Any] | None = None

    def __call__(
        self, eligible: EligibleSet, state: CustomerState, catalog: Catalog, rules: RuleSet
    ) -> Proposal:
        self.last_output = None
        if eligible.send_window is None:
            return Proposal(None, reason="No Offer: no send time left (max_send_delay_hours)")
        if not eligible.options:  # e.g. every paid option dropped and no Nudge on this Trigger
            return Proposal(None, reason="No Offer: the Rules leave no option")
        response = self.client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=[TOOL],
            tool_choice={"type": "auto", "disable_parallel_tool_use": True},
            output_config={"effort": EFFORT},
            messages=[
                {"role": "user", "content": user_prompt(eligible, state, catalog, rules, self.trigger)}
            ],
            timeout=TIMEOUT_SECONDS,
        )
        self.last_output = _tool_input(response)
        return to_proposal(self.last_output, eligible)


def make_agent_chooser(client: Any, model: str, trigger: TriggerKind | None = None) -> AgentChooser:
    return AgentChooser(client, model, trigger)


def _tool_input(response: Any) -> dict[str, Any]:
    if response.stop_reason == "refusal":
        raise AgentError("the agent refused")
    if response.stop_reason == "max_tokens":
        raise AgentError("the agent's answer was cut off at max_tokens")
    for block in response.content:
        if block.type == "tool_use" and block.name == TOOL_NAME:
            return dict(block.input)
    raise AgentError(f"the agent didn't call {TOOL_NAME}")


def to_proposal(raw: dict[str, Any], eligible: EligibleSet) -> Proposal:
    """The Proposal for the agent's tool input. Raises AgentError for an index outside the Eligible Set; every
    other problem is left for Validation to report.
    """
    index = raw["option_index"]
    reason = str(raw["reason"]).strip()[:MAX_REASON]
    if index == NO_OFFER_INDEX:
        return Proposal(None, reason=reason)
    if not isinstance(index, int) or not 0 <= index < len(eligible.options):
        raise AgentError(
            f"option_index {index} is not in the Eligible Set (0–{len(eligible.options) - 1} or -1)"
        )
    option = eligible.options[index]
    params = {name: float(value) for name, value in (raw.get("params") or {}).items() if value is not None}
    return Proposal(
        offer_type=option.offer_type,
        category=option.category,
        params=params,
        featured_product_ids=tuple(raw.get("featured_product_ids") or ()),
        send_at=eligible.send_window[0],
        caption=str(raw["caption"]).strip(),
        reason=reason,
    )


# --- The user message: everything that changes per Decision ------------------------------------


def user_prompt(
    eligible: EligibleSet,
    state: CustomerState,
    catalog: Catalog,
    rules: RuleSet,
    trigger: TriggerKind | None,
) -> str:
    now = eligible.at
    sections = [
        _trigger_section(state, now, trigger, eligible, rules),
        _customer_section(state, now, rules),
        _offers_section(state),
        _events_section(state, now, catalog),
        _products_section(state, now, catalog),
        _categories_section(catalog),
        _eligible_section(eligible),
    ]
    return "\n\n".join(sections)


def _trigger_section(
    state: CustomerState, now: datetime, trigger: TriggerKind | None, eligible: EligibleSet, rules: RuleSet
) -> str:
    what = TRIGGERS.get(trigger, "is being considered for an Offer")
    send_at = eligible.send_window[0]
    return (
        f"## Trigger\n{state.customer.id} {what}. Decision time: {_time(now)}.\n"
        f"An Offer would be sent at {_time(send_at)} and stay valid for {rules.offer_validity_days} days."
    )


def _customer_section(state: CustomerState, now: datetime, rules: RuleSet) -> str:
    c = state.customer
    orders = _recent(state, now, ("order",))
    lines = [
        f"## Customer {c.id}",
        (
            f"- Loyalty tier {c.loyalty_tier}, city tier {c.city_tier}, {c.device}, came via {c.channel}, "
            f"customer for {(now - c.signup_at).days} days."
        ),
        f"- Points: {c.points_balance} (worth ₹{c.points_balance * rules.point_value:,.0f})"
        + (f", expiring {_time(c.points_expire_at)}." if c.points_expire_at else "."),
    ]
    if orders:
        spent = sum(e.amount or 0 for e in orders)
        lines.append(
            f"- {len(orders)} orders in the last {RECENT_CATEGORY_DAYS} days, ₹{spent:,.0f} in total; "
            f"last order {(now - orders[0].at).days} days ago."
        )
    else:
        last = next((e for e in reversed(state.events) if e.kind == "order"), None)
        since = f"; last order {(now - last.at).days} days ago" if last else ""
        lines.append(f"- No orders in the last {RECENT_CATEGORY_DAYS} days{since}.")
    return "\n".join(lines)


def _offers_section(state: CustomerState) -> str:
    if not state.offers:
        return "## Past Offers\nNone."
    lines = ["## Past Offers (oldest first)"]
    for o in state.offers:
        name = f"{o.offer_type} {o.category}" if o.category else str(o.offer_type)
        lines.append(f"- {_time(o.created_at)} {name}: {o.status}")
    return "\n".join(lines)


def _events_section(state: CustomerState, now: datetime, catalog: Catalog) -> str:
    recent = _recent(state, now, None)
    if not recent:
        return f"## Events in the last {RECENT_CATEGORY_DAYS} days\nNone."
    counts = Counter(e.kind for e in recent)
    views = Counter(e.category for e in recent if e.kind == "product_view" and e.category)
    lines = [
        f"## Events in the last {RECENT_CATEGORY_DAYS} days",
        "Counts: " + ", ".join(f"{kind} {n}" for kind, n in sorted(counts.items())),
    ]
    if views:
        lines.append(
            "Product views by category: " + ", ".join(f"{cat} {n}" for cat, n in views.most_common())
        )
    loud = [e for e in recent if e.kind not in QUIET_KINDS][:MAX_RECENT_EVENTS]
    if loud:
        lines.append("Latest events other than sessions and views (newest first):")
        lines += [f"- {_time(e.at)} {e.kind}{_event_detail(e, catalog)}" for e in loud]
    return "\n".join(lines)


def _event_detail(event, catalog: Catalog) -> str:
    parts = []
    product = catalog.products.get(event.product_id) if event.product_id else None
    if product:
        parts.append(f"{product.id} {product.name}")
    elif event.category:
        parts.append(event.category)
    if event.amount is not None:
        parts.append(f"₹{event.amount:,.0f}" if event.kind != "points_earned" else f"{event.amount:g} points")
    return (" " + ", ".join(parts)) if parts else ""


def _products_section(state: CustomerState, now: datetime, catalog: Catalog) -> str:
    """Products the Customer carted or viewed lately: the only ones allowed as featured products."""
    seen: dict[str, set[str]] = {}
    for e in _recent(state, now, ("add_to_cart", "cart_abandoned", "product_view", "order")):
        if e.product_id in catalog.products:
            seen.setdefault(e.product_id, set()).add(e.kind)
    if not seen:
        return "## Recent products\nNone, so leave featured_product_ids empty."
    lines = ["## Recent products (newest first; featured products must come from here)"]
    for product_id in list(seen)[:MAX_SEEN_PRODUCTS]:
        p = catalog.products[product_id]
        lines.append(
            f"- {p.id} {p.name} ({p.category}, ₹{p.price:,.0f}): {', '.join(sorted(seen[product_id]))}"
        )
    return "\n".join(lines)


def _categories_section(catalog: Catalog) -> str:
    lines = ["## Categories (margin, average basket)"]
    lines += [
        f"- {c.name}: {c.margin_pct:g}% margin, ₹{c.avg_basket:,.0f} basket"
        for c in sorted(catalog.categories.values(), key=lambda c: c.name)
    ]
    return "\n".join(lines)


def _eligible_section(eligible: EligibleSet) -> str:
    lines = ["## Eligible Set"]
    for i, option in enumerate(eligible.options):
        name = f"{option.offer_type} {option.category}" if option.category else str(option.offer_type)
        ranges = "; ".join(
            f"{param} {_range(param, r.lo, r.hi)}"
            + (f" (Binding Rule: {option.binding_rules[param]})" if param in option.binding_rules else "")
            for param, r in option.ranges.items()
        )
        lines.append(
            f"[{i}] {name}: {ranges or 'no parameters'}; worst-case cost ₹{option.worst_case_cost:,.0f} at the top "
            "of its ranges; "
            f"{_lift(option.offer_type, option.estimated_lift)}"
        )
    lines.append(f"[{NO_OFFER_INDEX}] No Offer")
    return "\n".join(lines)


def _lift(offer_type: OfferType, estimated: float | None) -> str:
    if estimated is not None:
        return f"Estimated Lift {estimated:.1%} at full depth"
    return f"no Estimated Lift yet (prior guess: up to {PRIORS[offer_type].max_lift:.0%})"


def _range(param: str, lo: float, hi: float) -> str:
    if math.isinf(hi):
        return f"{_amount(param, lo)} or more"
    return f"{_amount(param, lo)}–{_amount(param, hi)}"


def _amount(param: str, value: float) -> str:
    unit = PARAM_UNITS.get(param, "")
    return f"₹{value:,.0f}" if unit == "₹" else f"{value:g}{unit}"


def _recent(state: CustomerState, now: datetime, kinds: tuple[str, ...] | None):
    """The Customer's events of the last 90 days, newest first. Events at the same time keep their recorded order,
    reversed, so a Stop then `/start` within one simulated minute shows the opt-in as the latest."""
    since = now - timedelta(days=RECENT_CATEGORY_DAYS)
    events = [e for e in state.events if since <= e.at <= now and (kinds is None or e.kind in kinds)]
    return sorted(events, key=lambda e: e.at)[::-1]


def _time(at: datetime) -> str:
    return at.strftime("%Y-%m-%d %H:%M")
