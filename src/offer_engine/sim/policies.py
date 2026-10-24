"""The four Policies the offline simulator compares (PLAN §5, QnA Q31, Q43): No Offers, Blanket 20%, Rules Only and
Rules + Agent.

A Policy's `chooser_factory` takes the run's `RunContext` and returns a `pipeline.ChooserFactory`, which the
offline run forces on every Decision through `pipeline.chooser_override`.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from offer_engine import pipeline
from offer_engine.choosers import rules_chooser
from offer_engine.domain import (
    Catalog,
    CustomerState,
    EligibleSet,
    OfferStatus,
    OfferType,
    Proposal,
    RuleSet,
    TriggerKind,
)
from offer_engine.sim.agent_cache import AgentCache

BLANKET_PCT = 20.0
TOP_CATEGORY_DAYS = 180
LIVE = (OfferStatus.QUEUED, OfferStatus.SENT, OfferStatus.CLAIMED)


@dataclass
class RunContext:
    """What a Policy may need: the sample the agent decides for and the agent's cache (None without an agent)."""

    sample: frozenset[str] = frozenset()
    agent: AgentCache | None = None


@dataclass(frozen=True)
class Policy:
    name: str
    label: str
    chooser_factory: Callable[[RunContext], pipeline.ChooserFactory]
    validate: bool = True
    sample_only: bool = False  # reported on the sample only
    needs_agent: bool = False


# --- No Offers ---------------------------------------------------------------------------------


def _no_offer(eligible: EligibleSet, state: CustomerState, catalog: Catalog, rules: RuleSet) -> Proposal:
    return Proposal(None, reason="No Offer: the No Offers Policy")


def _no_offers(ctx: RunContext) -> pipeline.ChooserFactory:
    return lambda state, trigger: _no_offer


# --- Blanket 20% -------------------------------------------------------------------------------


def blanket_choose(eligible: EligibleSet, state: CustomerState, catalog: Catalog, rules: RuleSet) -> Proposal:
    """20% off the Customer's top category, uncapped, unless they hold a live Offer (Q43). Ignores the Eligible
    Set; the pipeline skips Validation for this Policy and stops only for opt-out and the Holdout."""
    now = eligible.at
    if any(o.status in LIVE and o.expires_at > now for o in state.offers):
        return Proposal(None, reason="No Offer: holds a live Offer (Blanket 20%)")
    category = top_category(state, now, catalog)
    featured = rules_chooser.featured_products(state, now, catalog, category)
    return Proposal(
        offer_type=OfferType.PCT_CATEGORY,
        category=category,
        params={"pct": BLANKET_PCT, "cap": math.inf},
        featured_product_ids=featured,
        send_at=eligible.send_window[0] if eligible.send_window else now,
        caption=rules_chooser.caption(OfferType.PCT_CATEGORY, featured, category, catalog),
        reason="Blanket 20%",
    )


def top_category(state: CustomerState, now: datetime, catalog: Catalog) -> str:
    """The category of most of the Customer's orders in the last 180 days, else of most of their events, else the
    catalog's first. Ties go to the category named first."""
    since = now - timedelta(days=TOP_CATEGORY_DAYS)
    recent = [e for e in state.events if e.category in catalog.categories and since <= e.at <= now]
    for events in ([e for e in recent if e.kind == "order"], recent):
        if events:
            counts = Counter(e.category for e in events)
            return min(counts, key=lambda c: (-counts[c], c))
    return min(catalog.categories)


def _blanket(ctx: RunContext) -> pipeline.ChooserFactory:
    return lambda state, trigger: blanket_choose


# --- Rules Only and Rules + Agent ----------------------------------------------------------------


def _rules_only(ctx: RunContext) -> pipeline.ChooserFactory:
    return lambda state, trigger: rules_chooser.choose


class AgentForSample:
    """The agent for Customers in the sample, the rules chooser for the rest, so the budget runs down as it does
    under Rules Only. `prefetch` makes the sample's Daily Sweep calls concurrently."""

    def __init__(self, ctx: RunContext):
        if ctx.agent is None:
            raise ValueError(
                "the Rules + Agent Policy needs an agent (ANTHROPIC_API_KEY and FAST_AGENT_MODEL)"
            )
        self.sample = ctx.sample
        self.agent = ctx.agent

    def __call__(self, state: CustomerState, trigger: TriggerKind | None) -> pipeline.ChooserFn:
        if state.customer.id in self.sample:
            return self.agent.chooser(trigger)
        return rules_chooser.choose

    def prefetch(self, states, eligible, catalog, rules, trigger) -> None:
        self.agent.prefetch(
            [s for s in states if s.customer.id in self.sample], eligible, catalog, rules, trigger
        )


POLICIES = {
    p.name: p
    for p in (
        Policy("no_offers", "No Offers", _no_offers),
        Policy("blanket_20", "Blanket 20%", _blanket, validate=False),
        Policy("rules_only", "Rules Only", _rules_only),
        Policy("rules_plus_agent", "Rules + Agent", AgentForSample, sample_only=True, needs_agent=True),
    )
}
