"""The decision pipeline (ADR 0001, PLAN §3.5): Rules → chooser → Validation → Fallback → Decision log.

`default_chooser` and `default_lift_estimator` are separate on purpose: T11 changed only the first, T16 only the
second.
"""

from __future__ import annotations

import functools
import json
import secrets
import sqlite3
import string
from collections.abc import Callable, Iterable, Iterator
from dataclasses import replace
from datetime import datetime, timedelta

from offer_engine import caption_check
from offer_engine.budget import budget_state
from offer_engine.choosers import rules_chooser
from offer_engine.choosers.agent_chooser import make_agent_chooser
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
from offer_engine.rules import eligible_set, offer_cost
from offer_engine.rules_store import current_rules
from offer_engine.validation import validate

ChooserFn = Callable[[EligibleSet, CustomerState, Catalog, RuleSet], Proposal]
LiftEstimator = Callable[[CustomerState, EligibleOption], float | None]

# The parameter whose limit is the Decision's Binding Rule. Offer Types without parameters have none.
MAIN_PARAM = {
    OfferType.PCT_CATEGORY: "pct",
    OfferType.FLAT_ABOVE_MIN: "amount",
    OfferType.POINTS_MULTIPLIER: "multiplier",
}
FALLBACK_FAILED = "fallback_failed"
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


def default_lift_estimator() -> LiftEstimator:
    return _no_estimate


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
) -> Decision:
    """Decide for one Customer at `now`, write the Decision and, if an Offer was chosen, a `queued` Offer.

    The Decision's `validation` is None when nothing was proposed or rejected. Otherwise `ok` says whether the
    Decision's Offer passed, and `failures` lists every failure on the way, including a rejected proposal's
    before the Fallback took over.
    """
    catalog = load_catalog(conn)
    version, rules = current_rules(conn)
    state = load_customer_state(conn, customer_id, now)
    budget = budget_state(conn, rules, now)
    return _decide(conn, state, trigger, now, catalog, version, rules, budget, chooser, lift_estimator)


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
) -> Decision:
    customer_id = state.customer.id
    es = eligible_set(state, rules, budget, now, catalog)
    estimate = lift_estimator or default_lift_estimator()
    es = replace(es, options=tuple(replace(o, estimated_lift=estimate(state, o)) for o in es.options))

    def decision(chooser_used: Chooser, proposal: Proposal | None, binding: str | None, validation=None):
        reason = proposal.reason if proposal else ""
        return Decision(
            None, customer_id, now, trigger, chooser_used, None, reason, binding, version, validation
        )

    if es.short_circuit is not None:
        no_offer = Proposal(None, reason=f"No Offer: {es.short_circuit} ({es.binding_rule})")
        return _write(
            conn, decision(Chooser.RULES, no_offer, es.binding_rule), None, es, state, catalog, rules
        )

    primary = chooser or default_chooser(state, trigger)
    is_rules = primary is rules_chooser.choose
    chooser_used = Chooser.RULES if is_rules else Chooser.AGENT
    proposal, rejected = _attempt(primary, es, state, catalog, rules, budget, now)
    agent_output = getattr(primary, "last_output", None)
    failures: list[str] = []
    if rejected and is_rules:
        failures, rejected = rejected, []
    elif rejected:
        chooser_used = Chooser.FALLBACK
        proposal, failures = _attempt(rules_chooser.choose, es, state, catalog, rules, budget, now)
    if failures:
        # The rules chooser's own proposal failed Validation: a bug. Log it and send nothing.
        result = ValidationResult(False, tuple(rejected + failures))
        no_offer = Proposal(None, reason="No Offer: the rules chooser's proposal failed Validation")
        failed = decision(chooser_used, no_offer, FALLBACK_FAILED, result)
        return _write(conn, failed, None, es, state, catalog, rules, agent_output)

    validation = ValidationResult(True, tuple(rejected)) if proposal.offer_type or rejected else None
    binding = None
    if proposal.offer_type is not None:
        option = _option(es, proposal)
        binding = option.binding_rules.get(MAIN_PARAM.get(proposal.offer_type, ""))
    return _write(
        conn,
        decision(chooser_used, proposal, binding, validation),
        proposal,
        es,
        state,
        catalog,
        rules,
        agent_output,
    )


def _attempt(choose: ChooserFn, es, state, catalog, rules, budget, now) -> tuple[Proposal | None, list[str]]:
    """The chooser's Proposal and its Validation failures; an exception is a failure too."""
    try:
        proposal = choose(es, state, catalog, rules)
    except Exception as exc:  # noqa: BLE001 — the agent may be down; any error falls back
        return None, [f"chooser_error: {type(exc).__name__}: {exc}"]
    checker = functools.partial(caption_check.check, validity_days=rules.offer_validity_days)
    return proposal, list(validate(proposal, state, rules, budget, now, catalog, checker).failures)


def _option(es: EligibleSet, proposal: Proposal) -> EligibleOption:
    return next(
        o for o in es.options if o.offer_type == proposal.offer_type and o.category == proposal.category
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
) -> Decision:
    """Write the Offer (if any) and the Decision, with the agent's raw tool input if any, in one transaction."""
    offer_id = None
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
    return replace(decision, id=cur.lastrowid, offer_id=offer_id)


def _insert_offer(conn, decision: Decision, proposal: Proposal, es, state, catalog, rules) -> int:
    option = _option(es, proposal)
    focus = rules_chooser.focus_category(state, decision.at, catalog)
    worst_case = offer_cost(proposal.offer_type, proposal.category, proposal.params, catalog, rules)[0]
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
) -> Iterator[Decision]:
    """`decide` for each Customer in order, loading the catalog, Rules and budget once and states in batches.

    Each Offer written is added to the budget's `reserved` as `budget_state` would count it, so later Customers
    see what earlier ones used. Unknown IDs are skipped.
    """
    catalog = load_catalog(conn)
    version, rules = current_rules(conn)
    budget = budget_state(conn, rules, now)
    column = "worst_case_cost" if rules.budget_mode == BudgetMode.WORST_CASE else "expected_cost"
    ids = list(customer_ids)
    for i in range(0, len(ids), BATCH):
        batch = ids[i : i + BATCH]
        states = load_customer_states(conn, batch, now)
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
            )
            if d.offer_id is not None:
                cost = conn.execute(f"SELECT {column} FROM offers WHERE id = ?", (d.offer_id,)).fetchone()[0]
                budget = replace(budget, reserved=budget.reserved + cost)
            yield d
