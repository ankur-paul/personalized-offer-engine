"""Decision trace: every live Decision records why it came out as it did, stage by stage (T35)."""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from offer_engine import clock, pipeline
from offer_engine.budget import budget_state
from offer_engine.choosers import rules_chooser
from offer_engine.choosers.agent_chooser import PARAM_NAMES, AgentChooser
from offer_engine.cli import main
from offer_engine.customers import load_customer_state
from offer_engine.db import load_catalog
from offer_engine.domain import Chooser, RuleSet, TriggerKind
from offer_engine.rules import eligible_set, in_holdout
from offer_engine.trace import STAGES, Stage, Trace

NOW = clock.START + timedelta(hours=10)
CART = TriggerKind.CART_ABANDONED


class FakeClient:
    """Stands in for `anthropic.Anthropic`, answering every call with one `propose_offer` tool input."""

    def __init__(self, tool_input):
        self.messages = self
        self.tool_input = tool_input

    def create(self, **kwargs):
        block = SimpleNamespace(type="tool_use", name="propose_offer", input=self.tool_input)
        return SimpleNamespace(stop_reason="tool_use", content=[block])


@pytest.fixture
def customer_id(world) -> str:
    """A Customer outside the Holdout who carted something in the last 90 days."""
    since = (NOW - timedelta(days=90)).isoformat()
    rows = world.execute(
        "SELECT DISTINCT customer_id FROM events WHERE kind = 'add_to_cart' AND at >= ? ORDER BY customer_id",
        (since,),
    )
    return next(r[0] for r in rows if not in_holdout(r[0], RuleSet().holdout_pct))


def fake_agent(world, customer_id, scale: float = 1.0) -> AgentChooser:
    """An agent that proposes what the rules chooser would, with its parameters times `scale`."""
    state = load_customer_state(world, customer_id, NOW)
    catalog = load_catalog(world)
    es = eligible_set(state, RuleSet(), budget_state(world, RuleSet(), NOW), NOW, catalog)
    p = rules_chooser.choose(es, state, catalog, RuleSet())
    assert p.params, "the fixture Customer should get an Offer with parameters"
    index = next(
        i for i, o in enumerate(es.options) if o.offer_type == p.offer_type and o.category == p.category
    )
    params = {name: p.params[name] * scale if name in p.params else None for name in PARAM_NAMES}
    raw = {
        "option_index": index,
        "params": params,
        "featured_product_ids": list(p.featured_product_ids),
        "caption": p.caption,
        "reason": "keen on this category",
    }
    return AgentChooser(FakeClient(raw), "test-model", CART)


def stored(world, decision_id) -> Trace:
    row = world.execute("SELECT trace FROM decision_traces WHERE decision_id = ?", (decision_id,)).fetchone()
    return Trace.from_json(row[0])


def names(trace: Trace) -> list[str]:
    return [s.name for s in trace.stages]


def test_agent_decision_traces_every_stage_and_calls_the_listener_in_order(world, customer_id):
    heard: list[Stage] = []
    d = pipeline.decide(
        world, customer_id, CART, NOW, chooser=fake_agent(world, customer_id), on_stage=heard.append
    )
    assert d.chooser == Chooser.AGENT and d.offer_id is not None
    trace = stored(world, d.id)
    assert names(trace) == [s for s in STAGES if s != "fallback"]
    assert heard == trace.stages

    stage = {s.name: s for s in trace.stages}
    assert stage["trigger"].data["kind"] == "cart_abandoned"
    assert all(i["status"] == "passed" for i in stage["checks"].data["items"])
    assert stage["eligible_set"].data["options"] and stage["eligible_set"].data["send_window"]
    assert len(stage["valuation"].data["options"]) == len(stage["eligible_set"].data["options"])
    agent = stage["agent"].data
    assert agent["model"] == "test-model" and "## Eligible Set" in agent["prompt"]
    assert agent["output"]["reason"] == "keen on this category" and agent["seconds"] >= 0
    assert stage["validation"].data["ok"] and stage["validation"].data["caption_check"]["status"] == "passed"
    assert all(c["status"] == "passed" for c in stage["validation"].data["checks"])
    offer = world.execute("SELECT code FROM offers WHERE id = ?", (d.offer_id,)).fetchone()[0]
    assert stage["offer"].data["code"] == offer and stage["offer"].data["chooser"] == "agent"


def test_rejected_agent_proposal_adds_a_fallback_stage_naming_the_failures(world, customer_id):
    heard: list[str] = []
    agent = fake_agent(world, customer_id, scale=100)
    d = pipeline.decide(world, customer_id, CART, NOW, chooser=agent, on_stage=lambda s: heard.append(s.name))
    assert d.chooser == Chooser.FALLBACK and d.offer_id is not None
    trace = stored(world, d.id)
    assert names(trace) == list(STAGES) == heard

    stage = {s.name: s for s in trace.stages}
    assert not stage["validation"].data["ok"]
    failed = [c for c in stage["validation"].data["checks"] if c["status"] == "failed"]
    assert any(c["name"] == "params" for c in failed)
    fallback = stage["fallback"].data
    assert fallback["rejected"] == list(d.validation.failures)
    assert any(f.startswith("param_out_of_range") for f in fallback["rejected"])
    assert "param_out_of_range" in stage["fallback"].summary and fallback["ok"]
    assert stage["offer"].data["chooser"] == "fallback"


def test_failed_agent_call_is_traced_as_an_error_then_a_fallback(world, customer_id):
    def down(*args):
        raise TimeoutError("agent timed out")

    d = pipeline.decide(world, customer_id, CART, NOW, chooser=down)
    stage = {s.name: s for s in stored(world, d.id).stages}
    assert "agent timed out" in stage["agent"].data["error"]
    assert stage["validation"].data["checks"] == [
        {"name": "chooser", "status": "failed", "failures": ["chooser_error: TimeoutError: agent timed out"]}
    ]
    assert "fallback" in stage


def test_holdout_customer_trace_stops_at_checks(world):
    holdout = next(
        r[0] for r in world.execute("SELECT id FROM customers ORDER BY id") if in_holdout(r[0], 10.0)
    )
    d = pipeline.decide(world, holdout, CART, NOW)
    trace = stored(world, d.id)
    assert names(trace) == ["trigger", "customer", "checks", "offer"]
    checks = trace.stages[2]
    assert checks.data["binding_rule"] == "holdout_pct" and "holdout_pct" in checks.summary
    status = {i["name"]: i["status"] for i in checks.data["items"]}
    assert status["opt_out"] == "passed" and status["holdout"] == "stopped"
    assert status["fatigue_pause"] == "not reached"
    assert trace.stages[3].data["offer_type"] is None and "holdout" in trace.stages[3].summary


def test_rules_chooser_decision_skips_the_agent(world, customer_id):
    d = pipeline.decide(world, customer_id, CART, NOW)
    stage = {s.name: s for s in stored(world, d.id).stages}
    assert stage["agent"].summary == "skipped: no chat"
    assert "fallback" not in stage


def test_trace_json_round_trips(world, customer_id):
    d = pipeline.decide(world, customer_id, CART, NOW)
    trace = stored(world, d.id)
    assert Trace.from_json(trace.to_json()) == trace
    json.loads(trace.to_json())  # standard JSON: an open range is null, not Infinity
    assert "Infinity" not in trace.to_json()


def test_trace_false_stores_none_but_still_calls_the_listener(world, customer_id):
    heard = []
    d = pipeline.decide(world, customer_id, CART, NOW, trace=False, on_stage=heard.append)
    assert world.execute("SELECT COUNT(*) FROM decision_traces").fetchone()[0] == 0
    assert heard and heard[-1].name == "offer"
    with pipeline.chooser_override(lambda s, t: rules_chooser.choose, trace=False):
        list(pipeline.decide_many(world, [customer_id], TriggerKind.DAILY_SWEEP, NOW + timedelta(days=1)))
    assert world.execute("SELECT COUNT(*) FROM decision_traces").fetchone()[0] == 0
    assert d.id is not None


def test_decide_many_stores_full_traces_and_calls_the_listener(world):
    heard = []
    ids = [r[0] for r in world.execute("SELECT id FROM customers ORDER BY id LIMIT 5")]
    decisions = list(pipeline.decide_many(world, ids, TriggerKind.DAILY_SWEEP, NOW, on_stage=heard.append))
    traces = [stored(world, d.id) for d in decisions]
    assert len(traces) == 5 and all(names(t)[:3] == ["trigger", "customer", "checks"] for t in traces)
    assert [s.name for s in heard].count("trigger") == 5


# --- decisions explain -------------------------------------------------------------------------


@pytest.fixture
def world_env(world, clean_env, monkeypatch):
    path = world.execute("PRAGMA database_list").fetchone()[2]
    monkeypatch.setenv("DB_PATH", path)
    return world


def test_decisions_explain_prints_each_stage_title(world_env, customer_id, capsys):
    d = pipeline.decide(world_env, customer_id, CART, NOW)
    capsys.readouterr()
    assert main(["decisions", "explain", str(d.id)]) == 0
    out = capsys.readouterr().out
    for title in (
        "Trigger",
        "Customer",
        "Checks",
        "Eligible Set",
        "Valuation",
        "Agent",
        "Validation",
        "Offer",
    ):
        assert f"\n{title}\n" in f"\n{out}" or out.startswith(title), title
    assert "skipped: no chat" in out and "✓ holdout" in out


def test_decisions_explain_without_a_trace_says_so(world_env, customer_id, capsys):
    d = pipeline.decide(world_env, customer_id, CART, NOW)
    world_env.execute("DELETE FROM decision_traces")
    world_env.commit()
    assert main(["decisions", "explain", str(d.id)]) == 0
    assert "no trace" in capsys.readouterr().out


def test_decisions_explain_unknown_id(world_env):
    with pytest.raises(SystemExit, match="no Decision #999"):
        main(["decisions", "explain", "999"])


def test_decisions_without_a_subcommand_still_lists(world_env, customer_id, capsys):
    pipeline.decide(world_env, customer_id, CART, NOW)
    assert main(["decisions", "--last", "1"]) == 0
    assert customer_id in capsys.readouterr().out
