"""One real Claude call returns a usable proposal. Run with `uv run pytest -m live tests/test_agent_live.py`."""

from __future__ import annotations

from datetime import timedelta

import pytest

from offer_engine import clock
from offer_engine.budget import budget_state
from offer_engine.choosers import agent_chooser
from offer_engine.config import load_settings
from offer_engine.customers import load_customer_state
from offer_engine.db import load_catalog
from offer_engine.domain import Proposal, RuleSet, TriggerKind
from offer_engine.rules import eligible_set, in_holdout

NOW = clock.START + timedelta(hours=10)


@pytest.mark.live
def test_real_call_returns_a_parseable_proposal(world):
    import anthropic

    settings = load_settings()
    if not settings.anthropic_api_key or not settings.offer_agent_model:
        pytest.fail("set ANTHROPIC_API_KEY and OFFER_AGENT_MODEL in .env")
    since = (NOW - timedelta(days=90)).isoformat()
    rows = world.execute(
        "SELECT DISTINCT customer_id FROM events WHERE kind = 'add_to_cart' AND at >= ? ORDER BY customer_id",
        (since,),
    )
    cid = next(r[0] for r in rows if not in_holdout(r[0], RuleSet().holdout_pct))
    catalog = load_catalog(world)
    state = load_customer_state(world, cid, NOW)
    es = eligible_set(state, RuleSet(), budget_state(world, RuleSet(), NOW), NOW, catalog)

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=0)
    chooser = agent_chooser.make_agent_chooser(client, settings.offer_agent_model, TriggerKind.CART_ABANDONED)
    proposal = chooser(es, state, catalog, RuleSet())

    assert isinstance(proposal, Proposal) and proposal.reason
    assert set(chooser.last_output) == {"option_index", "params", "featured_product_ids", "caption", "reason"}
    if proposal.offer_type is not None:
        assert (proposal.offer_type, proposal.category) in {(o.offer_type, o.category) for o in es.options}
        assert proposal.caption
