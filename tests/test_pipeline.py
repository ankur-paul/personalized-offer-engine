"""Decision pipeline on a generated 50-Customer world (T09, PLAN §3.5, ADR 0001)."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from offer_engine import clock, pipeline
from offer_engine.budget import budget_state
from offer_engine.choosers import rules_chooser
from offer_engine.cli import main
from offer_engine.customers import load_customer_state, load_customer_states
from offer_engine.db import load_catalog
from offer_engine.domain import Chooser, OfferType, Proposal, RuleSet, TriggerKind
from offer_engine.rules import eligible_set, in_holdout
from offer_engine.rules_store import save_rules

NOW = clock.START + timedelta(hours=10)
CART = TriggerKind.CART_ABANDONED


def ids(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT id FROM customers ORDER BY id")]


@pytest.fixture
def holdout_id(world) -> str:
    return next(i for i in ids(world) if in_holdout(i, RuleSet().holdout_pct))


@pytest.fixture
def eligible_id(world) -> str:
    """A Customer outside the Holdout who carted something in the last 90 days."""
    since = (NOW - timedelta(days=90)).isoformat()
    rows = world.execute(
        "SELECT DISTINCT customer_id FROM events WHERE kind = 'add_to_cart' AND at >= ? ORDER BY customer_id",
        (since,),
    )
    return next(r[0] for r in rows if not in_holdout(r[0], RuleSet().holdout_pct))


def decision_row(conn, decision_id):
    return conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).fetchone()


def offer_row(conn, offer_id):
    return conn.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()


# --- Customer loader ---------------------------------------------------------------------------


def test_load_customer_state_reads_recent_events_offers_and_chat(world, eligible_id):
    world.execute("INSERT INTO chats VALUES (?, 4242, 'tester')", (eligible_id,))
    world.commit()
    pipeline.decide(world, eligible_id, CART, NOW)
    state = load_customer_state(world, eligible_id, NOW)
    assert state.customer.id == eligible_id
    assert state.events and all(NOW - timedelta(days=180) <= e.at <= NOW for e in state.events)
    assert [e.at for e in state.events] == sorted(e.at for e in state.events)
    live = [o for o in state.offers if o.created_at == NOW]
    assert len(live) == 1 and all(o.created_at < NOW for o in state.offers if o is not live[0])
    assert state.chat is not None and state.chat.chat_id == 4242
    earlier = load_customer_state(world, eligible_id, NOW - timedelta(days=30))
    assert all(o.created_at <= NOW - timedelta(days=30) for o in earlier.offers)
    assert all(e.at <= NOW - timedelta(days=30) for e in earlier.events)


def test_load_customer_states_in_bulk(world):
    all_ids = ids(world)
    states = load_customer_states(world, [*all_ids, "NOPE"], NOW)
    assert set(states) == set(all_ids)
    one = load_customer_state(world, all_ids[3], NOW)
    assert states[all_ids[3]] == one


def test_unknown_customer_raises(world):
    with pytest.raises(KeyError):
        load_customer_state(world, "NOPE", NOW)


# --- decide ------------------------------------------------------------------------------------


def test_holdout_customer_gets_no_offer(world, holdout_id):
    d = pipeline.decide(world, holdout_id, CART, NOW)
    assert d.offer_id is None and d.binding_rule == "holdout_pct" and d.chooser == Chooser.RULES
    assert "holdout" in d.reason
    row = decision_row(world, d.id)
    assert row["validation_ok"] is None and row["offer_id"] is None
    assert world.execute("SELECT COUNT(*) FROM offers WHERE source = 'live'").fetchone()[0] == 0


def test_eligible_customer_gets_a_queued_offer_inside_the_eligible_set(world, eligible_id):
    catalog = load_catalog(world)
    state = load_customer_state(world, eligible_id, NOW)
    es = eligible_set(state, RuleSet(), budget_state(world, RuleSet(), NOW), NOW, catalog)

    d = pipeline.decide(world, eligible_id, CART, NOW)
    assert d.chooser == Chooser.RULES and d.validation.ok and d.validation.failures == ()
    offer = offer_row(world, d.offer_id)
    assert offer["status"] == "queued" and offer["source"] == "live" and offer["rule_version"] == 0
    assert re.fullmatch(r"POE-[A-Z0-9]{6}", offer["code"])
    option = next(
        o for o in es.options if o.offer_type == offer["offer_type"] and o.category == offer["category"]
    )
    params = json.loads(offer["params"])
    assert set(params) == set(option.ranges)
    for name, value in params.items():
        assert option.ranges[name].lo <= value <= option.ranges[name].hi
    send_at = datetime.fromisoformat(offer["send_at"])
    assert send_at == es.send_window[0]
    assert datetime.fromisoformat(offer["expires_at"]) == send_at + timedelta(days=3)
    assert 0 <= offer["expected_cost"] <= offer["worst_case_cost"] <= RuleSet().per_offer_cost_cap
    assert offer["caption"] and not re.search(r"\d", offer["caption"])
    row = decision_row(world, d.id)
    assert row["offer_id"] == d.offer_id and row["validation_ok"] == 1 and row["trigger"] == "cart_abandoned"


def test_binding_rule_is_the_main_parameters_limit(world, eligible_id):
    d = pipeline.decide(world, eligible_id, CART, NOW)
    offer = offer_row(world, d.offer_id)
    if offer["offer_type"] in (OfferType.FREE_SHIPPING, OfferType.NUDGE):
        assert d.binding_rule is None
    else:
        assert d.binding_rule in RuleSet().to_dict()


def test_out_of_range_proposal_falls_back_with_failures_stored(world, eligible_id):
    def greedy(es, state, catalog, rules):
        p = rules_chooser.choose(es, state, catalog, rules)
        return (
            replace(p, params={k: v * 100 for k, v in p.params.items()})
            if p.params
            else replace(p, send_at=None)
        )

    d = pipeline.decide(world, eligible_id, CART, NOW, chooser=greedy)
    assert d.chooser == Chooser.FALLBACK and d.offer_id is not None
    assert d.validation.ok
    failures = json.loads(decision_row(world, d.id)["validation_failures"])
    assert failures and all(
        re.match(r"(param_out_of_range|cost_over_cap|over_budget|send_at_missing):", f) for f in failures
    )


def test_chooser_raising_falls_back(world, eligible_id):
    def down(*args):
        raise TimeoutError("agent timed out")

    d = pipeline.decide(world, eligible_id, CART, NOW, chooser=down)
    assert d.chooser == Chooser.FALLBACK and d.offer_id is not None
    assert d.validation.failures == ("chooser_error: TimeoutError: agent timed out",)


def test_valid_agent_proposal_is_recorded_as_agent(world, eligible_id):
    d = pipeline.decide(world, eligible_id, CART, NOW, chooser=lambda *a: rules_chooser.choose(*a))
    assert d.chooser == Chooser.AGENT and d.offer_id is not None and d.validation.failures == ()


def test_agent_no_offer_is_logged_without_validation(world, eligible_id):
    d = pipeline.decide(world, eligible_id, CART, NOW, chooser=lambda *a: Proposal(None, reason="Sure Thing"))
    assert (
        d.chooser == Chooser.AGENT and d.offer_id is None and d.validation is None and d.binding_rule is None
    )
    assert d.reason == "Sure Thing"


def test_fallback_failing_validation_is_logged_as_a_bug(world, eligible_id, monkeypatch):
    bad = Proposal(OfferType.NUDGE, category="nope", send_at=NOW, caption="Hi", reason="bad")
    monkeypatch.setattr(rules_chooser, "choose", lambda *a: bad)
    d = pipeline.decide(world, eligible_id, CART, NOW, chooser=lambda *a: bad)
    assert d.chooser == Chooser.FALLBACK and d.offer_id is None and d.binding_rule == "fallback_failed"
    assert not d.validation.ok and len(d.validation.failures) >= 2
    assert decision_row(world, d.id)["validation_ok"] == 0


def test_lift_estimator_fills_every_option(world, eligible_id):
    seen = []

    def spy(es, state, catalog, rules):
        seen.append(es)
        return rules_chooser.choose(es, state, catalog, rules)

    d = pipeline.decide(world, eligible_id, CART, NOW, chooser=spy, lift_estimator=lambda s, o: -0.01)
    assert all(o.estimated_lift == -0.01 for o in seen[0].options)
    assert d.offer_id is None and "no option has positive expected value" in d.reason


def test_frequency_cap_reached_after_n_triggers(world, eligible_id):
    cap = RuleSet().frequency_cap_count
    decisions = [pipeline.decide(world, eligible_id, CART, NOW + timedelta(hours=i)) for i in range(cap + 1)]
    assert all(d.offer_id is not None for d in decisions[:cap])
    assert decisions[cap].offer_id is None and decisions[cap].binding_rule == "frequency_cap_count"


def test_queued_offers_reserve_budget(world, eligible_id):
    d = pipeline.decide(world, eligible_id, CART, NOW)
    worst = offer_row(world, d.offer_id)["worst_case_cost"]
    assert budget_state(world, RuleSet(), NOW).reserved == pytest.approx(worst)


def test_decision_records_the_current_rule_version(world, eligible_id):
    version = save_rules(world, RuleSet(margin_floor_pct=6.0), author="test")
    d = pipeline.decide(world, eligible_id, CART, NOW)
    assert d.rule_version == version == offer_row(world, d.offer_id)["rule_version"]


def test_defaults_are_the_rules_chooser_and_no_estimate(world, eligible_id):
    state = load_customer_state(world, eligible_id, NOW)
    assert pipeline.default_chooser(state) is rules_chooser.choose
    assert pipeline.default_lift_estimator()(state, None) is None


# --- CLI ---------------------------------------------------------------------------------------


@pytest.fixture
def world_env(world, clean_env, monkeypatch):
    path = world.execute("PRAGMA database_list").fetchone()[2]
    monkeypatch.setenv("DB_PATH", path)
    return world


def test_cli_trigger_cart_abandoned_then_decisions(world_env, eligible_id, capsys):
    assert main(["trigger", "cart-abandoned", eligible_id]) == 0
    out = capsys.readouterr().out
    assert re.search(r"^Decision: \w+ .*· chooser=rules · binding: \w+ · rule v0 · valid$", out, re.MULTILINE)
    assert re.search(r"Offer POE-[A-Z0-9]{6} queued", out)
    event = world_env.execute(
        "SELECT * FROM events WHERE customer_id = ? AND kind = 'cart_abandoned' ORDER BY at DESC LIMIT 1",
        (eligible_id,),
    ).fetchone()
    assert event["at"] == clock.START.isoformat() and event["product_id"]

    assert main(["decisions", "--last", "5"]) == 0
    out = capsys.readouterr().out
    assert eligible_id in out and "cart_abandoned" in out and "chooser=rules" in out


def test_cli_trigger_holdout_prints_no_offer(world_env, holdout_id, capsys):
    assert main(["trigger", "cart-abandoned", holdout_id]) == 0
    assert "Decision: No Offer · chooser=rules · binding: holdout_pct" in capsys.readouterr().out


def test_cli_trigger_unknown_customer(world_env):
    with pytest.raises(SystemExit, match="no Customer"):
        main(["trigger", "cart-abandoned", "NOPE"])


def test_cli_decisions_filters_by_customer(world_env, eligible_id, holdout_id, capsys):
    pipeline.decide(world_env, eligible_id, CART, NOW)
    pipeline.decide(world_env, holdout_id, CART, NOW)
    main(["decisions", "--customer", holdout_id])
    out = capsys.readouterr().out
    assert holdout_id in out and eligible_id not in out


def test_cli_eligible_customer(world_env, eligible_id, capsys):
    assert main(["eligible", "--customer", eligible_id]) == 0
    out = capsys.readouterr().out
    assert f"Eligible Set for {eligible_id}" in out and "rule v0" in out and "nudge" in out
