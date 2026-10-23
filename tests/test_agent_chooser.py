"""Agent chooser in the decision pipeline with a fake Claude client (T11, PLAN §3.5, ADR 0001)."""

from __future__ import annotations

import json
import re
from datetime import timedelta
from types import SimpleNamespace

import pytest

from offer_engine import clock, pipeline
from offer_engine.budget import budget_state
from offer_engine.choosers import agent_chooser, rules_chooser
from offer_engine.cli import main
from offer_engine.config import Settings
from offer_engine.customers import load_customer_state
from offer_engine.db import load_catalog
from offer_engine.domain import Chooser, RuleSet, TriggerKind
from offer_engine.rules import eligible_set, in_holdout

NOW = clock.START + timedelta(hours=10)
CART = TriggerKind.CART_ABANDONED


class FakeClient:
    """Stands in for `anthropic.Anthropic`: returns one canned response, or raises."""

    def __init__(self, tool_input=None, *, error=None, stop_reason="tool_use", content=None):
        self.messages = self
        self.calls = []
        self.error = error
        self.stop_reason = stop_reason
        self.content = (
            content
            if content is not None
            else [SimpleNamespace(type="tool_use", name="propose_offer", input=tool_input)]
        )

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(stop_reason=self.stop_reason, content=self.content)


@pytest.fixture
def customer_id(world) -> str:
    """A chat-attached Customer outside the Holdout who carted something in the last 90 days."""
    since = (NOW - timedelta(days=90)).isoformat()
    rows = world.execute(
        "SELECT DISTINCT customer_id FROM events WHERE kind = 'add_to_cart' AND at >= ? ORDER BY customer_id",
        (since,),
    )
    cid = next(r[0] for r in rows if not in_holdout(r[0], RuleSet().holdout_pct))
    world.execute("INSERT INTO chats VALUES (?, 777, 'bot')", (cid,))
    world.commit()
    return cid


@pytest.fixture
def agent(monkeypatch):
    """Turn the agent on for chat-attached Customers; `agent(client)` sets the fake it talks to."""

    def use(client, model="test-model"):
        monkeypatch.setattr(
            pipeline, "load_settings", lambda: Settings(anthropic_api_key="test-key", offer_agent_model=model)
        )
        monkeypatch.setattr(pipeline, "_client", lambda key: client)
        return client

    return use


def eligible(world, customer_id):
    catalog = load_catalog(world)
    state = load_customer_state(world, customer_id, NOW)
    es = eligible_set(state, RuleSet(), budget_state(world, RuleSet(), NOW), NOW, catalog)
    return es, state, catalog


def good_input(world, customer_id) -> dict:
    """What a sensible agent would send: the rules chooser's pick, as tool input."""
    es, state, catalog = eligible(world, customer_id)
    p = rules_chooser.choose(es, state, catalog, RuleSet())
    index = next(
        i for i, o in enumerate(es.options) if (o.offer_type, o.category) == (p.offer_type, p.category)
    )
    params = {name: p.params.get(name) for name in agent_chooser.PARAM_NAMES}
    return {
        "option_index": index,
        "params": params,
        "featured_product_ids": list(p.featured_product_ids),
        "caption": "That pick from your cart is still waiting, with a little help from us.",
        "reason": "Recent cart in this category; the smallest discount that should tip it.",
    }


def stored(world, decision_id):
    row = world.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).fetchone()
    return json.loads(row["validation_failures"]), row["agent_output"] and json.loads(row["agent_output"])


# --- Through the pipeline ----------------------------------------------------------------------


def test_valid_proposal_is_decided_by_the_agent(world, customer_id, agent):
    raw = good_input(world, customer_id)
    client = agent(FakeClient(raw))
    d = pipeline.decide(world, customer_id, CART, NOW)
    assert d.chooser == Chooser.AGENT and d.offer_id is not None and d.validation.ok
    assert d.reason == raw["reason"]
    offer = world.execute("SELECT * FROM offers WHERE id = ?", (d.offer_id,)).fetchone()
    assert offer["caption"] == raw["caption"]
    assert json.loads(offer["featured_product_ids"]) == raw["featured_product_ids"]
    assert stored(world, d.id) == ([], raw)
    assert len(client.calls) == 1 and client.calls[0]["model"] == "test-model"


def test_param_out_of_range_falls_back_with_failures_stored(world, customer_id, agent):
    raw = good_input(world, customer_id)
    raw["params"] = {k: (v * 100 if v is not None else None) for k, v in raw["params"].items()}
    if all(v is None for v in raw["params"].values()):
        pytest.skip("the chosen option takes no parameters")
    agent(FakeClient(raw))
    d = pipeline.decide(world, customer_id, CART, NOW)
    assert d.chooser == Chooser.FALLBACK and d.offer_id is not None and d.validation.ok
    failures, output = stored(world, d.id)
    assert any(f.startswith("param_out_of_range:") for f in failures)
    assert output == raw


def test_caption_with_a_number_falls_back(world, customer_id, agent):
    raw = {**good_input(world, customer_id), "caption": "Grab 50% off before it's gone!"}
    agent(FakeClient(raw))
    d = pipeline.decide(world, customer_id, CART, NOW)
    assert d.chooser == Chooser.FALLBACK and d.offer_id is not None
    failures, _ = stored(world, d.id)
    assert any(f.startswith("number_mismatch:") for f in failures)


@pytest.mark.parametrize("error", [TimeoutError("timed out"), ConnectionError("API down")])
def test_client_error_falls_back(world, customer_id, agent, error):
    agent(FakeClient(error=error))
    d = pipeline.decide(world, customer_id, CART, NOW)
    assert d.chooser == Chooser.FALLBACK and d.offer_id is not None
    failures, output = stored(world, d.id)
    assert failures == [f"chooser_error: {type(error).__name__}: {error}"] and output is None


def test_no_offer_by_the_agent(world, customer_id, agent):
    raw = {**good_input(world, customer_id), "option_index": -1, "reason": "Buys every week anyway."}
    agent(FakeClient(raw))
    d = pipeline.decide(world, customer_id, CART, NOW)
    assert d.chooser == Chooser.AGENT and d.offer_id is None and d.validation is None
    assert d.reason == "Buys every week anyway."
    assert stored(world, d.id)[1] == raw


@pytest.mark.parametrize(
    "client, failure",
    [
        (FakeClient(stop_reason="refusal", content=[]), "the agent refused"),
        (FakeClient(stop_reason="max_tokens", content=[]), "cut off at max_tokens"),
        (
            FakeClient(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="Hi")]),
            "didn't call",
        ),
    ],
)
def test_unusable_answers_fall_back(world, customer_id, agent, client, failure):
    agent(client)
    d = pipeline.decide(world, customer_id, CART, NOW)
    assert d.chooser == Chooser.FALLBACK and d.offer_id is not None
    assert failure in stored(world, d.id)[0][0]


def test_index_outside_the_eligible_set_falls_back(world, customer_id, agent):
    raw = {**good_input(world, customer_id), "option_index": 99}
    agent(FakeClient(raw))
    d = pipeline.decide(world, customer_id, CART, NOW)
    failures, output = stored(world, d.id)
    assert d.chooser == Chooser.FALLBACK and "option_index 99" in failures[0] and output == raw


def test_missing_model_falls_back(world, customer_id, agent):
    agent(FakeClient(), model=None)
    d = pipeline.decide(world, customer_id, CART, NOW)
    assert d.chooser == Chooser.FALLBACK
    assert stored(world, d.id)[0] == ["chooser_error: RuntimeError: OFFER_AGENT_MODEL is not set in .env"]


def test_customer_without_a_chat_gets_the_rules_chooser(world, customer_id, agent):
    client = agent(FakeClient(good_input(world, customer_id)))
    world.execute("DELETE FROM chats")
    world.commit()
    d = pipeline.decide(world, customer_id, CART, NOW)
    assert d.chooser == Chooser.RULES and client.calls == []


def test_without_an_api_key_the_rules_chooser_decides(world, customer_id):
    state = load_customer_state(world, customer_id, NOW)
    assert state.chat is not None
    assert pipeline.default_chooser(state, CART) is rules_chooser.choose


def test_rules_chooser_caption_is_checked_too(world, customer_id, monkeypatch):
    """The Caption Check runs inside Validation for every chooser."""
    original = rules_chooser.choose

    def loud(*args):
        from dataclasses import replace

        return replace(original(*args), caption="Hurry, ends tonight!")

    d = pipeline.decide(world, customer_id, CART, NOW, chooser=loud)
    failures, _ = stored(world, d.id)
    assert d.chooser == Chooser.FALLBACK
    assert any(f.startswith("deadline_mismatch:") for f in failures)
    assert any(f.startswith("invented_urgency:") for f in failures)


# --- The request -------------------------------------------------------------------------------


def test_request_shape(world, customer_id):
    es, state, catalog = eligible(world, customer_id)
    client = FakeClient(good_input(world, customer_id))
    proposal = agent_chooser.make_agent_chooser(client, "m", CART)(es, state, catalog, RuleSet())
    assert proposal.send_at == es.send_window[0]
    call = client.calls[0]
    assert call["timeout"] == agent_chooser.TIMEOUT_SECONDS
    assert call["tool_choice"]["type"] == "auto"
    assert [t["name"] for t in call["tools"]] == ["propose_offer"] and call["tools"][0]["strict"]
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call["system"][0]["text"] == agent_chooser.SYSTEM_PROMPT
    assert "left a cart" in call["messages"][0]["content"]


def test_no_send_window_is_no_offer_without_a_call(world, customer_id):
    from dataclasses import replace

    es, state, catalog = eligible(world, customer_id)
    client = FakeClient()
    p = agent_chooser.make_agent_chooser(client, "m")(
        replace(es, send_window=None), state, catalog, RuleSet()
    )
    assert p.offer_type is None and client.calls == []


def test_null_params_are_dropped_and_reason_clipped(world, customer_id):
    es, *_ = eligible(world, customer_id)
    raw = {
        "option_index": 0,
        "params": dict.fromkeys(agent_chooser.PARAM_NAMES),
        "featured_product_ids": [],
        "caption": "  Hello  ",
        "reason": "x" * 500,
    }
    p = agent_chooser.to_proposal(raw, es)
    assert p.params == {} and p.caption == "Hello" and len(p.reason) == agent_chooser.MAX_REASON


# --- CLI ---------------------------------------------------------------------------------------


def test_cli_shows_the_agents_rejected_proposal(world, customer_id, agent, clean_env, monkeypatch, capsys):
    monkeypatch.setenv("DB_PATH", world.execute("PRAGMA database_list").fetchone()[2])
    agent(FakeClient({**good_input(world, customer_id), "caption": "Hurry!"}))
    assert main(["trigger", "cart-abandoned", customer_id]) == 0
    out = capsys.readouterr().out
    assert "chooser=fallback" in out and "valid (Fallback)" in out
    assert re.search(r"agent's rejected proposal: \{.*\"caption\": \"Hurry!\"", out)
    assert "invented_urgency: hurry" in out
