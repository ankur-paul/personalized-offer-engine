"""The agent's prompt: every option, the Customer's own products, nothing from the simulator (T11, ADR 0002)."""

from __future__ import annotations

import json
import re
from datetime import timedelta

from offer_engine import clock
from offer_engine.budget import budget_state
from offer_engine.choosers import agent_chooser
from offer_engine.customers import load_customer_state, load_customer_states
from offer_engine.db import load_catalog
from offer_engine.domain import RuleSet, TriggerKind
from offer_engine.rules import eligible_set

NOW = clock.START + timedelta(hours=10)
SIM_NAME = re.compile(r"\bsim_\w+")


def prompts(world):
    """(Eligible Set, user prompt) for every Customer in the world who isn't short-circuited."""
    catalog = load_catalog(world)
    budget = budget_state(world, RuleSet(), NOW)
    ids = [r[0] for r in world.execute("SELECT id FROM customers ORDER BY id")]
    for state in load_customer_states(world, ids, NOW).values():
        es = eligible_set(state, RuleSet(), budget, NOW, catalog)
        if es.short_circuit is None and es.send_window is not None:
            yield (
                es,
                state,
                agent_chooser.user_prompt(es, state, catalog, RuleSet(), TriggerKind.CART_ABANDONED),
            )


def test_prompt_lists_every_option_and_no_offer(world):
    checked = 0
    for es, _, prompt in prompts(world):
        for i, option in enumerate(es.options):
            name = f"{option.offer_type} {option.category}" if option.category else str(option.offer_type)
            assert f"[{i}] {name}:" in prompt
            for rule in option.binding_rules.values():
                assert rule in prompt
        assert "[-1] No Offer" in prompt
        checked += 1
    assert checked > 10


def test_prompt_lists_only_products_the_customer_saw(world):
    for _, state, prompt in prompts(world):
        section = prompt.split("## Recent products", 1)[1].split("##", 1)[0]
        listed = re.findall(r"^- (\w+) ", section, re.MULTILINE)
        seen = {e.product_id for e in state.events if e.at >= NOW - timedelta(days=90)}
        assert set(listed) <= seen
        assert len(listed) <= agent_chooser.MAX_SEEN_PRODUCTS


def test_nothing_names_simulator_data(world):
    texts = [agent_chooser.SYSTEM_PROMPT, json.dumps(agent_chooser.TOOL)]
    texts += [prompt for _, _, prompt in prompts(world)]
    assert not any(SIM_NAME.search(t) for t in texts)


def test_customer_state_has_no_simulator_fields(world):
    """The prompt is built from CustomerState; hidden traits never reach it."""
    cid = world.execute("SELECT id FROM customers LIMIT 1").fetchone()[0]
    state = load_customer_state(world, cid, NOW)
    assert not SIM_NAME.search(repr(state))


def test_system_prompt_is_static():
    """The cached prefix is the same for every Decision: no dates, IDs or amounts in it."""
    assert not re.search(r"C\d{5}|20\d\d-\d\d-\d\d|₹\d", agent_chooser.SYSTEM_PROMPT)
