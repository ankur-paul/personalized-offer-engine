"""The decision pipeline (ADR 0001, PLAN §3.5): Rules → chooser → Validation → Fallback → Decision log.

`default_chooser` and `default_lift_estimator` are separate on purpose: T11 changed only the first, T16 only the
second. `chooser_override` lets the offline Policy simulator (T26) force its chooser on Decisions the Triggers and
the Daily Sweep start. Each Decision stores its trace (T35) and hands each stage to `on_stage` as it finishes.
"""

from __future__ import annotations

import functools
import json
import secrets
import sqlite3
import string
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from offer_engine import caption_check
from offer_engine import trace as decision_trace
from offer_engine.budget import budget_state
from offer_engine.choosers import rules_chooser
from offer_engine.choosers.agent_chooser import AgentChooser, make_agent_chooser, user_prompt
from offer_engine.config import load_settings
from offer_engine.customers import load_customer_state, load_customer_states
from offer_engine.db import load_catalog
from offer_engine.domain import (
    BudgetMode,
    BudgetState,
    Catalog,
    Chooser,
    CustomerState,
    Decision,
    EligibleOption,
    EligibleSet,
    OfferSource,
    OfferStatus,
    OfferType,
    Proposal,
    RuleSet,
    TriggerKind,
    ValidationResult,
)
from offer_engine.lift import segment_lift
from offer_engine.rules import eligible_set, offer_cost
from offer_engine.rules_store import current_rules
from offer_engine.trace import StageListener
from offer_engine.validation import validate

ChooserFn = Callable[[EligibleSet, CustomerState, Catalog, RuleSet], Proposal]
LiftEstimator = Callable[[CustomerState, EligibleOption], float | None]
ChooserFactory = Callable[[CustomerState, TriggerKind | None], ChooserFn]
# Called before `decide_many` decides a batch with the batch's states, a function giving a state's Eligible Set as
# the batch sees it at its start, the catalog, the Rules and the trigger. The Rules + Agent Policy uses it to make
# its agent calls concurrently.
Prefetch = Callable[
    [list[CustomerState], Callable[[CustomerState], EligibleSet], Catalog, RuleSet, TriggerKind], None
]

# The parameter whose limit is the Decision's Binding Rule. Offer Types without parameters have none.
MAIN_PARAM = {
    OfferType.PCT_CATEGORY: "pct",
    OfferType.FLAT_ABOVE_MIN: "amount",
    OfferType.POINTS_MULTIPLIER: "multiplier",
}
FALLBACK_FAILED = "fallback_failed"
CHOOSER_ERROR = "chooser_error"
# Short-circuits that stop a Decision even when Validation is off: nothing overrides opt-out or the Holdout.
ALWAYS_STOP = ("opt_out", "holdout")
CODE_PREFIX = "POE-"
CODE_ALPHABET = string.ascii_uppercase + string.digits


def default_chooser(state: CustomerState, trigger: TriggerKind | None = None) -> ChooserFn:
    """The agent for chat-attached Customers when `ANTHROPIC_API_KEY` is set, else the rules chooser."""
    settings = load_settings()
    if state.chat is None or not settings.anthropic_api_key:
        return rules_chooser.choose
    if not settings.offer_agent_model:
        return _missing_model
    return make_agent_chooser(_client(settings.anthropic_api_key), settings.offer_agent_model, trigger)


@functools.cache
def _client(api_key: str):
    import anthropic

    # No retries: a failed call falls back to the rules chooser within the agent's timeout.
    return anthropic.Anthropic(api_key=api_key, max_retries=0)


def _missing_model(*args) -> Proposal:
    raise RuntimeError("OFFER_AGENT_MODEL is not set in .env")


@dataclass(frozen=True)
class Override:
    choose_for: ChooserFactory
    validate: bool = True
    prefetch: Prefetch | None = None
    trace: bool = True


_override: ContextVar[Override | None] = ContextVar("chooser_override", default=None)


@contextmanager
def chooser_override(
    choose_for: ChooserFactory,
    *,
    validate: bool = True,
    prefetch: Prefetch | None = None,
    trace: bool = True,
) -> Iterator[None]:
    """Inside the block, a Decision with no explicit `chooser` uses `choose_for(state, trigger)` instead of
    `default_chooser`, `validate=False` turns Validation off as `decide(..., validate=False)` does, and
    `trace=False` stores no traces as `decide(..., trace=False)` does."""
    token = _override.set(Override(choose_for, validate, prefetch, trace))
    try:
        yield
    finally:
        _override.reset(token)


def default_lift_estimator(conn: sqlite3.Connection, now: datetime) -> LiftEstimator:
    """Estimated Lift v1 per segment once `offer-engine lift fit` has run, else none (the choosers use priors)."""
    fitted = segment_lift.load(conn, now)
    return fitted.estimate if fitted else _no_estimate


def _no_estimate(state: CustomerState, option: EligibleOption) -> float | None:
    return None


def decide(
    conn: sqlite3.Connection,
    customer_id: str,
    trigger: TriggerKind,
    now: datetime,
    *,
    chooser: ChooserFn | None = None,
    lift_estimator: LiftEstimator | None = None,
    validate: bool = True,
    on_stage: StageListener | None = None,
    trace: bool = True,
) -> Decision:
    """Decide for one Customer at `now`, write the Decision and, if an Offer was chosen, a `queued` Offer.

    The Decision's `validation` is None when nothing was proposed or rejected. Otherwise `ok` says whether the
    Decision's Offer passed, and `failures` lists every failure on the way, including a rejected proposal's
    before the Fallback took over.

    `validate=False` is for the Blanket 20% Policy only (T26): the chooser's Proposal is written as it is, and
    only opt-out and the Holdout stop it.

    `on_stage` gets each trace stage as it finishes. `trace=False` stores no trace, for the offline Policy
    simulator and Preview impact.
    """
    catalog = load_catalog(conn)
    version, rules = current_rules(conn)
    state = load_customer_state(conn, customer_id, now)
    budget = budget_state(conn, rules, now)
    return _decide(
        conn,
        state,
        trigger,
        now,
        catalog,
        version,
        rules,
        budget,
        chooser,
        lift_estimator,
        validate,
        on_stage,
        trace,
    )


def _decide(
    conn: sqlite3.Connection,
    state: CustomerState,
    trigger: TriggerKind,
    now: datetime,
    catalog: Catalog,
    version: int,
    rules: RuleSet,
    budget: BudgetState,
    chooser: ChooserFn | None,
    lift_estimator: LiftEstimator | None,
    validate: bool = True,
    on_stage: StageListener | None = None,
    trace: bool = True,
) -> Decision:
    customer_id = state.customer.id
    override = _override.get()
    if override is not None:
        validate = validate and override.validate
        trace = trace and override.trace
        chooser = chooser or override.choose_for(state, trigger)
    rec = decision_trace.Recorder(on_stage, keep=trace)
    rec.add(decision_trace.trigger_stage, trigger, state, now)
    rec.add(decision_trace.customer_stage, state, now)
    es = _eligible(state, rules, budget, now, catalog, lift_estimator or default_lift_estimator(conn, now))
    rec.add(decision_trace.checks_stage, state, rules, budget, now, es)

    def decision(chooser_used: Chooser, proposal: Proposal | None, binding: str | None, validation=None):
        reason = proposal.reason if proposal else ""
        return Decision(
            None, customer_id, now, trigger, chooser_used, None, reason, binding, version, validation
        )

    if es.short_circuit is not None and (validate or es.short_circuit in ALWAYS_STOP):
        no_offer = Proposal(None, reason=f"No Offer: {es.short_circuit} ({es.binding_rule})")
        return _write(
            conn, decision(Chooser.RULES, no_offer, es.binding_rule), None, es, state, catalog, rules, rec=rec
        )

    rec.add(decision_trace.eligible_set_stage, es)
    rec.add(decision_trace.valuation_stage, es, state, catalog, rules)
    primary = chooser or default_chooser(state, trigger)
    if not validate:
        started = time.perf_counter()
        proposal = primary(es, state, catalog, rules)
        _trace_chooser(rec, primary, es, state, catalog, rules, time.perf_counter() - started, None)
        rec.add(decision_trace.validation_stage, None)
        return _write(
            conn, decision(Chooser.RULES, proposal, None), proposal, es, state, catalog, rules, rec=rec
        )
    is_rules = primary is rules_chooser.choose
    chooser_used = Chooser.RULES if is_rules else Chooser.AGENT
    started = time.perf_counter()
    proposal, result = _attempt(primary, es, state, catalog, rules, budget, now)
    _trace_chooser(rec, primary, es, state, catalog, rules, time.perf_counter() - started, result)
    rec.add(decision_trace.validation_stage, result)
    agent_output = getattr(primary, "last_output", None)
    rejected, failures = list(result.failures), []
    if rejected and is_rules:
        failures, rejected = rejected, []
    elif rejected:
        chooser_used = Chooser.FALLBACK
        proposal, fallback = _attempt(rules_chooser.choose, es, state, catalog, rules, budget, now)
        failures = list(fallback.failures)
        rec.add(decision_trace.fallback_stage, rejected, proposal, fallback)
    if failures:
        # The rules chooser's own proposal failed Validation: a bug. Log it and send nothing.
        result = ValidationResult(False, tuple(rejected + failures))
        no_offer = Proposal(None, reason="No Offer: the rules chooser's proposal failed Validation")
        failed = decision(chooser_used, no_offer, FALLBACK_FAILED, result)
        return _write(conn, failed, None, es, state, catalog, rules, agent_output, rec)

    validation = ValidationResult(True, tuple(rejected)) if proposal.offer_type or rejected else None
    binding = None
    if proposal.offer_type is not None:
        binding = _option(es, proposal).binding_rules.get(MAIN_PARAM.get(proposal.offer_type, ""))
    return _write(
        conn,
        decision(chooser_used, proposal, binding, validation),
        proposal,
        es,
        state,
        catalog,
        rules,
        agent_output,
        rec,
    )


def _trace_chooser(
    rec: decision_trace.Recorder,
    primary: ChooserFn,
    es: EligibleSet,
    state: CustomerState,
    catalog: Catalog,
    rules: RuleSet,
    seconds: float,
    result: ValidationResult | None,
) -> None:
    """The agent stage: what the agent was asked and answered, or why the rules chooser decided instead."""
    if not rec.active:
        return
    if primary is rules_chooser.choose:
        reason = "no chat" if state.chat is None else "the rules chooser decides"
        rec.add(decision_trace.agent_skipped_stage, reason)
        return
    prompt = None
    if isinstance(primary, AgentChooser) and es.send_window is not None:
        prompt = user_prompt(es, state, catalog, rules, primary.trigger)
    failures = result.failures if result else ()
    error = next((f for f in failures if f.startswith(CHOOSER_ERROR)), None)
    output = getattr(primary, "last_output", None)
    rec.add(decision_trace.agent_stage, getattr(primary, "model", None), prompt, output, seconds, error)


def _eligible(
    state: CustomerState,
    rules: RuleSet,
    budget: BudgetState,
    now: datetime,
    catalog: Catalog,
    estimate: LiftEstimator,
) -> EligibleSet:
    """The Eligible Set with each option's Estimated Lift."""
    es = eligible_set(state, rules, budget, now, catalog)
    return replace(es, options=tuple(replace(o, estimated_lift=estimate(state, o)) for o in es.options))


def _attempt(
    choose: ChooserFn, es, state, catalog, rules, budget, now
) -> tuple[Proposal | None, ValidationResult]:
    """The chooser's Proposal and its Validation result; an exception is a failure too, with no checks run."""
    try:
        proposal = choose(es, state, catalog, rules)
    except Exception as exc:  # noqa: BLE001 — the agent may be down; any error falls back
        return None, ValidationResult(False, (f"{CHOOSER_ERROR}: {type(exc).__name__}: {exc}",))
    checker = functools.partial(caption_check.check, validity_days=rules.offer_validity_days)
    return proposal, validate(proposal, state, rules, budget, now, catalog, checker)


def _option(es: EligibleSet, proposal: Proposal) -> EligibleOption | None:
    """The option the Proposal took; None only for an unvalidated Proposal from outside the Eligible Set."""
    return next(
        (o for o in es.options if o.offer_type == proposal.offer_type and o.category == proposal.category),
        None,
    )


def _write(
    conn: sqlite3.Connection,
    decision: Decision,
    proposal: Proposal | None,
    es: EligibleSet,
    state: CustomerState,
    catalog: Catalog,
    rules: RuleSet,
    agent_output: dict | None = None,
    rec: decision_trace.Recorder | None = None,
) -> Decision:
    """Write the Offer (if any) and the Decision, with the agent's raw tool input if any and its trace, in one
    transaction. The trace's `offer` stage reaches the listener once the transaction commits."""
    offer_id = None
    offer_stage = None
    with conn:
        if proposal is not None and proposal.offer_type is not None:
            offer_id = _insert_offer(conn, decision, proposal, es, state, catalog, rules)
        v = decision.validation
        cur = conn.execute(
            "INSERT INTO decisions (customer_id, at, trigger, chooser, offer_id, reason, binding_rule, rule_version,"
            " validation_ok, validation_failures, agent_output) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                decision.customer_id,
                _iso(decision.at),
                decision.trigger,
                decision.chooser,
                offer_id,
                decision.reason,
                decision.binding_rule,
                decision.rule_version,
                None if v is None else int(v.ok),
                json.dumps(list(v.failures) if v else []),
                None if agent_output is None else json.dumps(agent_output, ensure_ascii=False),
            ),
        )
        if rec is not None and rec.active:
            offer = _offer_facts(conn, offer_id)
            args = (proposal, decision.reason, str(decision.chooser), decision.binding_rule, offer)
            offer_stage = rec.add(decision_trace.offer_stage, *args, notify=False)
            kept = rec.trace()
            if kept is not None:
                conn.execute(
                    "INSERT INTO decision_traces (decision_id, trace) VALUES (?, ?)",
                    (cur.lastrowid, kept.to_json()),
                )
    if rec is not None:
        rec.notify(offer_stage)
    return replace(decision, id=cur.lastrowid, offer_id=offer_id)


def _offer_facts(conn: sqlite3.Connection, offer_id: int | None) -> dict | None:
    """The written Offer's code, expiry and costs, for the trace."""
    if offer_id is None:
        return None
    row = conn.execute(
        "SELECT code, expires_at, worst_case_cost, expected_cost FROM offers WHERE id = ?", (offer_id,)
    ).fetchone()
    return {
        "code": row[0],
        "expires_at": row[1],
        "worst_case_cost": round(row[2], 2),
        "expected_cost": round(row[3], 2),
    }


def _insert_offer(conn, decision: Decision, proposal: Proposal, es, state, catalog, rules) -> int:
    focus = rules_chooser.focus_category(state, decision.at, catalog)
    worst_case = offer_cost(proposal.offer_type, proposal.category, proposal.params, catalog, rules)[0]
    option = _option(es, proposal) or EligibleOption(
        proposal.offer_type, proposal.category, {}, {}, worst_case_cost=worst_case
    )
    expected = rules_chooser.assess(option, proposal.params, catalog, rules, focus).expected_cost
    expires_at = proposal.send_at + timedelta(days=rules.offer_validity_days)
    while True:
        try:
            cur = conn.execute(
                "INSERT INTO offers (code, customer_id, offer_type, category, params, featured_product_ids,"
                " created_at, send_at, expires_at, caption, rule_version, worst_case_cost, expected_cost, status,"
                " source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    new_code(),
                    decision.customer_id,
                    proposal.offer_type,
                    proposal.category,
                    json.dumps(proposal.params),
                    json.dumps(list(proposal.featured_product_ids)),
                    _iso(decision.at),
                    _iso(proposal.send_at),
                    _iso(expires_at),
                    proposal.caption,
                    decision.rule_version,
                    worst_case,
                    expected,
                    OfferStatus.QUEUED,
                    OfferSource.LIVE,
                ),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError as exc:
            if "offers.code" not in str(exc):
                raise


def new_code() -> str:
    return CODE_PREFIX + "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="seconds")


# Customers whose states are loaded at once by `decide_many`.
BATCH = 500


def decide_many(
    conn: sqlite3.Connection,
    customer_ids: Iterable[str],
    trigger: TriggerKind,
    now: datetime,
    *,
    chooser: ChooserFn | None = None,
    lift_estimator: LiftEstimator | None = None,
    validate: bool = True,
    on_stage: StageListener | None = None,
    trace: bool = True,
) -> Iterator[Decision]:
    """`decide` for each Customer in order, loading the catalog, Rules, budget and Estimated Lift once and states in
    batches.

    Each Offer written is added to the budget's `reserved` as `budget_state` would count it, so later Customers
    see what earlier ones used. Unknown IDs are skipped. Under a `chooser_override` with a `prefetch`, each batch
    is handed to it before its Decisions.
    """
    catalog = load_catalog(conn)
    version, rules = current_rules(conn)
    budget = budget_state(conn, rules, now)
    lift_estimator = lift_estimator or default_lift_estimator(conn, now)
    column = "worst_case_cost" if rules.budget_mode == BudgetMode.WORST_CASE else "expected_cost"
    ids = list(customer_ids)
    for i in range(0, len(ids), BATCH):
        batch = ids[i : i + BATCH]
        states = load_customer_states(conn, batch, now)
        override = _override.get()
        if override is not None and override.prefetch is not None and chooser is None:
            eligible = functools.partial(
                _eligible, rules=rules, budget=budget, now=now, catalog=catalog, estimate=lift_estimator
            )
            override.prefetch(
                [states[cid] for cid in batch if cid in states], eligible, catalog, rules, trigger
            )
        for customer_id in batch:
            if customer_id not in states:
                continue
            d = _decide(
                conn,
                states[customer_id],
                trigger,
                now,
                catalog,
                version,
                rules,
                budget,
                chooser,
                lift_estimator,
                validate,
                on_stage,
                trace,
            )
            if d.offer_id is not None:
                cost = conn.execute(f"SELECT {column} FROM offers WHERE id = ?", (d.offer_id,)).fetchone()[0]
                budget = replace(budget, reserved=budget.reserved + cost)
            yield d
