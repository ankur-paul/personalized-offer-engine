"""The Decision trace (T35, PLAN "Assumed › Decision trace"): why a Decision came out as it did, stage by stage.

The pipeline builds each Stage as it finishes and hands it to an optional listener, so the live engine page can
animate a Decision as it happens. A trace holds only what the pipeline sees, never Ground Truth (ADR 0002).
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from offer_engine.choosers import rules_chooser
from offer_engine.choosers.agent_chooser import TRIGGERS
from offer_engine.domain import (
    BudgetState,
    Catalog,
    CustomerState,
    EligibleSet,
    Proposal,
    RuleSet,
    TriggerKind,
    ValidationResult,
)
from offer_engine.rules import RECENT_CATEGORY_DAYS, fatigue_paused_until, in_holdout
from offer_engine.validation import failed_check

STAGES = (
    "trigger",
    "customer",
    "checks",
    "eligible_set",
    "valuation",
    "agent",
    "validation",
    "fallback",
    "offer",
)
TITLES = {
    "trigger": "Trigger",
    "customer": "Customer",
    "checks": "Checks",
    "eligible_set": "Eligible Set",
    "valuation": "Valuation",
    "agent": "Agent",
    "validation": "Validation",
    "fallback": "Fallback",
    "offer": "Offer",
}

# Check statuses: a check before the stop passed, the stop stopped, and the checks after it never ran.
PASSED, STOPPED, NOT_REACHED, FAILED = "passed", "stopped", "not reached", "failed"


@dataclass(frozen=True)
class Stage:
    name: str
    title: str
    summary: str
    data: dict[str, Any]


@dataclass(frozen=True)
class Trace:
    stages: list[Stage]

    def to_json(self) -> str:
        # Not `asdict`: its deep copy of every stage's data was half the cost of tracing the Daily Sweep.
        stages = [
            {"name": s.name, "title": s.title, "summary": s.summary, "data": s.data} for s in self.stages
        ]
        return json.dumps(stages, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> Trace:
        return cls([Stage(**s) for s in json.loads(text)])


StageListener = Callable[[Stage], None]


class Recorder:
    """Collects a Decision's stages and calls the listener after each. Inactive (no trace kept, no listener), it
    builds nothing, so the offline Policy simulator pays nothing for tracing."""

    def __init__(self, on_stage: StageListener | None, keep: bool):
        self.on_stage = on_stage
        self.keep = keep
        self.stages: list[Stage] = []

    @property
    def active(self) -> bool:
        return self.keep or self.on_stage is not None

    def add(self, build: Callable[..., Stage], *args: Any, notify: bool = True) -> Stage | None:
        """Build the stage with `build(*args)` and keep it; `notify=False` leaves calling the listener to
        `notify`, for a stage built inside a transaction."""
        if not self.active:
            return None
        stage = build(*args)
        self.stages.append(stage)
        if notify:
            self.notify(stage)
        return stage

    def notify(self, stage: Stage | None) -> None:
        if stage is not None and self.on_stage is not None:
            self.on_stage(stage)

    def trace(self) -> Trace | None:
        return Trace(self.stages) if self.keep else None


def _stage(name: str, summary: str, **data: Any) -> Stage:
    return Stage(name, TITLES[name], summary, data)


# --- Before the chooser ------------------------------------------------------------------------


def trigger_stage(trigger: TriggerKind, state: CustomerState, now: datetime) -> Stage:
    what = TRIGGERS.get(trigger, "is being considered for an Offer")
    return _stage(
        "trigger",
        f"{state.customer.id} {what} ({_time(now)})",
        kind=str(trigger),
        customer_id=state.customer.id,
        at=_iso(now),
    )


def customer_stage(state: CustomerState, now: datetime) -> Stage:
    c = state.customer
    since = now - timedelta(days=RECENT_CATEGORY_DAYS)
    orders = [e for e in state.events if e.kind == "order" and since <= e.at <= now]
    chat = str(state.chat.kind) if state.chat else None
    summary = (
        f"{c.loyalty_tier} tier, city tier {c.city_tier}, {len(orders)} orders in {RECENT_CATEGORY_DAYS} days, "
        f"{len(state.offers)} past Offers, " + (f"chat: {chat}" if chat else "no chat")
    )
    return _stage(
        "customer",
        summary,
        loyalty_tier=c.loyalty_tier,
        city_tier=c.city_tier,
        device=c.device,
        channel=c.channel,
        days_since_signup=(now - c.signup_at).days,
        orders_90d=len(orders),
        spent_90d=round(sum(e.amount or 0 for e in orders), 2),
        points_balance=c.points_balance,
        past_offers=len(state.offers),
        chat=chat,
    )


def checks_stage(
    state: CustomerState, rules: RuleSet, budget: BudgetState, now: datetime, es: EligibleSet
) -> Stage:
    """Each check that can stop all Offers, in the Rules engine's order. Which one stopped comes from the Eligible
    Set; the details are for reading only."""
    c = state.customer
    paused = fatigue_paused_until(state, rules)
    recent = sum(
        1 for o in state.offers if now - timedelta(days=rules.frequency_cap_days) < o.created_at <= now
    )
    redeemed = [o.redeemed_at for o in state.offers if o.redeemed_at is not None and o.redeemed_at <= now]
    signed_up = (now - c.signup_at).days
    remaining = max(rules.weekly_budget - budget.spent - budget.reserved, 0.0)
    checks = [
        ("opt_out", "opt_out", "opted out" if c.opted_out else "not opted out"),
        (
            "holdout",
            "holdout_pct",
            f"{'inside' if in_holdout(c.id, rules.holdout_pct) else 'outside'} the {rules.holdout_pct:g}% Holdout",
        ),
        (
            "fatigue_pause",
            "fatigue_dismissals",
            f"paused until {_time(paused)}" if paused and now < paused else "not paused",
        ),
        (
            "frequency_cap",
            "frequency_cap_count",
            f"{recent} of {rules.frequency_cap_count} Offers in {rules.frequency_cap_days} days",
        ),
        (
            "cooldown",
            "cooldown_days_after_redemption",
            f"last redeemed {_time(max(redeemed))}" if redeemed else "no Redemptions",
        ),
        (
            "eligibility",
            "min_days_since_signup",
            f"signed up {signed_up} days ago (needs {rules.min_days_since_signup})",
        ),
    ]
    items, status = [], PASSED
    for name, rule, detail in checks:
        if name == es.short_circuit:
            items.append({"name": name, "rule": rule, "status": STOPPED, "detail": detail})
            status = NOT_REACHED
        else:
            items.append({"name": name, "rule": rule, "status": status, "detail": detail})
    items.append(
        {
            "name": "budget",
            "rule": "weekly_budget",
            "status": status,
            "detail": f"₹{remaining:,.0f} of ₹{rules.weekly_budget:,.0f} left this week",
        }
    )
    if es.short_circuit is None:
        summary = "every check passed"
    else:
        summary = f"stopped by {es.short_circuit} ({es.binding_rule})"
    return _stage("checks", summary, items=items, stopped_by=es.short_circuit, binding_rule=es.binding_rule)


def eligible_set_stage(es: EligibleSet) -> Stage:
    options = [
        {
            "offer_type": str(o.offer_type),
            "category": o.category,
            "ranges": {p: [_finite(r.lo), _finite(r.hi)] for p, r in o.ranges.items()},
            "binding_rules": dict(o.binding_rules),
            "worst_case_cost": round(o.worst_case_cost, 2),
            "estimated_lift": o.estimated_lift,
        }
        for o in es.options
    ]
    window = [_iso(es.send_window[0]), _iso(es.send_window[1])] if es.send_window else None
    summary = f"{len(options)} options"
    if es.dropped:
        summary += f", {len(es.dropped)} dropped"
    summary += (
        f"; send window {_time(es.send_window[0])}–{es.send_window[1]:%H:%M}"
        if es.send_window
        else "; no send window left"
    )
    binding = sorted({r for o in es.options for r in o.binding_rules.values()})
    if binding:
        summary += f"; Binding Rules: {', '.join(binding)}"
    return _stage("eligible_set", summary, options=options, dropped=dict(es.dropped), send_window=window)


def valuation_stage(es: EligibleSet, state: CustomerState, catalog: Catalog, rules: RuleSet) -> Stage:
    """The rules chooser's best parameters and value per option, whoever decides."""
    focus = rules_chooser.focus_category(state, es.at, catalog)
    options, best = [], None
    for i, option in enumerate(es.options):
        top = None
        for params in rules_chooser.candidate_params(option, catalog, focus):
            a = rules_chooser.assess(option, params, catalog, rules, focus)
            if top is None or a.value > top[1].value:
                top = (params, a)
        params, a = top
        options.append(
            {
                "offer_type": str(option.offer_type),
                "category": option.category,
                "params": params,
                "lift": round(a.lift, 4),
                "redeem_chance": round(a.redeem_chance, 4),
                "margin": round(a.margin, 2),
                "cost_if_redeemed": round(a.cost_if_redeemed, 2),
                "value": round(a.value, 2),
            }
        )
        if best is None or a.value > options[best]["value"]:
            best = i
    if best is None or options[best]["value"] <= 0:
        summary = "no option has positive value"
    else:
        summary = f"best: {_option_text(options[best])} worth ₹{options[best]['value']:,.1f}"
    return _stage("valuation", summary, options=options, best=best)


# --- The chooser and Validation ----------------------------------------------------------------


def agent_skipped_stage(reason: str) -> Stage:
    return _stage("agent", f"skipped: {reason}", skipped=reason)


def agent_stage(
    model: str | None, prompt: str | None, output: dict | None, seconds: float, error: str | None
) -> Stage:
    if error:
        summary = f"failed after {seconds:.1f}s: {error}"
    elif output is None:
        summary = f"answered in {seconds:.1f}s with no tool input"
    elif output.get("option_index") == -1:
        summary = f"chose No Offer in {seconds:.1f}s"
    else:
        summary = f"chose option {output.get('option_index')} in {seconds:.1f}s"
    if model:
        summary = f"{model} {summary}"
    return _stage(
        "agent", summary, model=model, prompt=prompt, output=output, seconds=round(seconds, 3), error=error
    )


def validation_stage(result: ValidationResult | None) -> Stage:
    """Each check `validate` ran, passed or failed, with the Caption Check's result on its own. None means
    Validation was off."""
    if result is None:
        return _stage("validation", "skipped: Validation is off", checks=[], ok=None, caption_check=None)
    items = _check_items(result)
    caption = next((i for i in items if i["name"] == "caption_check"), None)
    if not result.checks and not result.failures:
        summary = "nothing to validate (No Offer)"
    elif result.ok:
        summary = f"all {len(result.checks)} checks passed"
    else:
        summary = f"failed: {'; '.join(result.failures)}"
    return _stage("validation", summary, checks=items, ok=result.ok, caption_check=caption)


def fallback_stage(rejected: list[str], proposal: Proposal | None, result: ValidationResult) -> Stage:
    """The agent's proposal was rejected or its call failed; the rules chooser took over."""
    took = _proposal_text(proposal)
    summary = f"agent rejected ({'; '.join(rejected)}); rules chooser chose {took}"
    if not result.ok:
        summary += ", which failed Validation too"
    return _stage(
        "fallback", summary, rejected=list(rejected), proposal=took, checks=_check_items(result), ok=result.ok
    )


def _check_items(result: ValidationResult) -> list[dict[str, Any]]:
    failed: dict[str, list[str]] = {}
    for f in result.failures:
        failed.setdefault(failed_check(f), []).append(f)
    items = [
        {"name": c, "status": FAILED if c in failed else PASSED, "failures": failed.get(c, [])}
        for c in result.checks
    ]
    # A failure from outside `validate` (the chooser raised) belongs to no check that ran.
    items += [
        {"name": "chooser", "status": FAILED, "failures": [f]}
        for f in result.failures
        if failed_check(f) not in result.checks and f.startswith("chooser_error")
    ]
    return items


# --- The outcome -------------------------------------------------------------------------------


def offer_stage(
    proposal: Proposal | None,
    reason: str,
    chooser: str,
    binding_rule: str | None,
    offer: dict[str, Any] | None,
) -> Stage:
    """`offer` is the written Offer's code, expiry and costs; None for No Offer."""
    if offer is None or proposal is None or proposal.offer_type is None:
        return _stage("offer", reason or "No Offer", offer_type=None, reason=reason, chooser=chooser)
    terms = _proposal_text(proposal)
    summary = (
        f"{terms} · send {_time(proposal.send_at)} · worst ₹{offer['worst_case_cost']:,.0f}"
        f" · by {chooser}" + (f" · Binding Rule {binding_rule}" if binding_rule else "")
    )
    return _stage(
        "offer",
        summary,
        offer_type=str(proposal.offer_type),
        category=proposal.category,
        params=dict(proposal.params),
        featured_product_ids=list(proposal.featured_product_ids),
        caption=proposal.caption,
        send_at=_iso(proposal.send_at),
        reason=reason,
        chooser=chooser,
        binding_rule=binding_rule,
        **offer,
    )


def _proposal_text(proposal: Proposal | None) -> str:
    if proposal is None or proposal.offer_type is None:
        return "No Offer"
    return _option_text(
        {"offer_type": str(proposal.offer_type), "category": proposal.category, "params": proposal.params}
    )


def _option_text(option: dict[str, Any]) -> str:
    params = " ".join(f"{k}={v:g}" for k, v in option["params"].items())
    return " ".join(p for p in (option["offer_type"], option["category"], params) if p)


def _finite(value: float) -> float | None:
    """JSON has no infinity; an open upper bound is null."""
    return value if math.isfinite(value) else None


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="seconds")


def _time(at: datetime) -> str:
    return at.strftime("%Y-%m-%d %H:%M")
