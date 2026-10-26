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


def test_decide_many_matches_decide_one_by_one(world, world_template, tmp_path):
    """A budget that runs out mid-way: `decide_many` must reserve each Offer as `decide`'s fresh query does."""
    import shutil

    from offer_engine.db import connect

    shutil.copy(world_template, tmp_path / "other.db")
    other = connect(tmp_path / "other.db")
    order = list(reversed(ids(world)))
    for conn in (world, other):
        save_rules(conn, RuleSet(weekly_budget=400.0), author="test")
    many = list(pipeline.decide_many(world, [*order, "NOPE"], TriggerKind.DAILY_SWEEP, NOW))
    single = [pipeline.decide(other, cid, TriggerKind.DAILY_SWEEP, NOW) for cid in order]

    def summary(conn, decisions):
        offers = [offer_row(conn, d.offer_id) if d.offer_id else None for d in decisions]
        return [
            (
                d.customer_id,
                d.reason,
                d.binding_rule,
                o and (o["offer_type"], o["params"], o["worst_case_cost"]),
            )
            for d, o in zip(decisions, offers, strict=True)
        ]

    assert summary(world, many) == summary(other, single)
    reserved = budget_state(world, RuleSet(), NOW).reserved
    assert reserved == budget_state(other, RuleSet(), NOW).reserved
    paid = [s[3][2] for s in summary(world, many) if s[3] and s[3][2] > 0]
    assert paid and 400.0 - reserved < min(paid)  # the budget ran out part-way
    other.close()


def test_decide_many_loads_estimated_lift_once(world, monkeypatch):
    calls = []
    real = pipeline.segment_lift.load
    monkeypatch.setattr(pipeline.segment_lift, "load", lambda conn, now: calls.append(now) or real(conn, now))
    list(pipeline.decide_many(world, ids(world), TriggerKind.DAILY_SWEEP, NOW))
    assert len(calls) == 1


def test_decision_records_the_current_rule_version(world, eligible_id):
    version = save_rules(world, RuleSet(margin_floor_pct=6.0), author="test")
    d = pipeline.decide(world, eligible_id, CART, NOW)
    assert d.rule_version == version == offer_row(world, d.offer_id)["rule_version"]


def test_defaults_are_the_rules_chooser_and_no_estimate(world, eligible_id):
    state = load_customer_state(world, eligible_id, NOW)
    assert pipeline.default_chooser(state) is rules_chooser.choose
    assert pipeline.default_lift_estimator(world, NOW)(state, None) is None


# --- Policy overrides (T26) ----------------------------------------------------------------------


def outside_the_eligible_set(es, state, catalog, rules) -> Proposal:
    """50% off with no cap: no Rule allows it."""
    category = min(catalog.categories)
    return Proposal(OfferType.PCT_CATEGORY, category, {"pct": 50.0, "cap": 1e9}, (), es.at, "Hi", "test")


def test_validate_false_writes_the_proposal_as_it_is(world, eligible_id):
    d = pipeline.decide(world, eligible_id, CART, NOW, chooser=outside_the_eligible_set, validate=False)
    offer = offer_row(world, d.offer_id)
    assert json.loads(offer["params"]) == {"pct": 50.0, "cap": 1e9}
    assert d.chooser == Chooser.RULES and d.validation is None and d.binding_rule is None
    assert offer["worst_case_cost"] == 1e9


def test_validate_false_ignores_every_short_circuit_but_opt_out_and_holdout(world, eligible_id, holdout_id):
    cap = RuleSet().frequency_cap_count
    for i in range(cap + 1):
        d = pipeline.decide(
            world,
            eligible_id,
            CART,
            NOW + timedelta(hours=i),
            chooser=outside_the_eligible_set,
            validate=False,
        )
        assert d.offer_id is not None
    held = pipeline.decide(world, holdout_id, CART, NOW, chooser=outside_the_eligible_set, validate=False)
    assert held.offer_id is None and held.binding_rule == "holdout_pct"
    world.execute("UPDATE customers SET opted_out = 1 WHERE id = ?", (eligible_id,))
    out = pipeline.decide(world, eligible_id, CART, NOW, chooser=outside_the_eligible_set, validate=False)
    assert out.offer_id is None and out.binding_rule == "opt_out"


def test_validation_stays_on_by_default(world, eligible_id):
    d = pipeline.decide(world, eligible_id, CART, NOW, chooser=outside_the_eligible_set)
    assert d.chooser == Chooser.FALLBACK and d.validation.failures


def test_chooser_override_forces_the_chooser_on_decide_and_decide_many(world, eligible_id):
    seen = []

    def no_offer(es, state, catalog, rules):
        seen.append(state.customer.id)
        return Proposal(None, reason="forced")

    with pipeline.chooser_override(lambda state, trigger: no_offer):
        assert pipeline.decide(world, eligible_id, CART, NOW).reason == "forced"
        many = list(pipeline.decide_many(world, ids(world), TriggerKind.DAILY_SWEEP, NOW + timedelta(days=1)))
    assert all(d.offer_id is None for d in many)
    assert eligible_id in seen and len(seen) > 1
    assert pipeline.decide(world, eligible_id, CART, NOW + timedelta(days=2)).reason != "forced"


def test_chooser_override_can_turn_validation_off(world, eligible_id):
    with pipeline.chooser_override(lambda state, trigger: outside_the_eligible_set, validate=False):
        d = pipeline.decide(world, eligible_id, CART, NOW)
    assert json.loads(offer_row(world, d.offer_id)["params"])["pct"] == 50.0


def test_prefetch_sees_each_batch_and_its_eligible_sets_before_deciding(world, monkeypatch):
    monkeypatch.setattr(pipeline, "BATCH", 20)
    batches = []

    def prefetch(states, eligible, catalog, rules, trigger):
        batches.append([(s.customer.id, eligible(s).customer_id) for s in states])

    with pipeline.chooser_override(lambda state, trigger: rules_chooser.choose, prefetch=prefetch):
        list(pipeline.decide_many(world, ids(world), TriggerKind.DAILY_SWEEP, NOW))
    assert [len(b) for b in batches] == [20, 20, 10]
    assert all(cid == es_id for b in batches for cid, es_id in b)


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


def test_cli_trigger_fires_once_per_simulated_time(world_env, eligible_id, capsys):
    assert main(["trigger", "cart-abandoned", eligible_id]) == 0
    with pytest.raises(SystemExit, match="already abandoned a cart"):
        main(["trigger", "cart-abandoned", eligible_id])
    query = "SELECT COUNT(*) FROM {} WHERE customer_id = ? AND {} >= ?"
    start = clock.START.isoformat()
    assert world_env.execute(query.format("decisions", "at"), (eligible_id, start)).fetchone()[0] == 1
    assert world_env.execute(query.format("events", "at"), (eligible_id, start)).fetchone()[0] == 1
    clock.set_now(world_env, clock.START + timedelta(hours=1))
    assert main(["trigger", "cart-abandoned", eligible_id]) == 0


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


# --- Repeatable Offer codes (T36) --------------------------------------------------------------


@pytest.fixture
def demo_seed(monkeypatch):
    def use(seed):
        settings = replace(pipeline.load_settings(), demo_seed=seed)
        monkeypatch.setattr(pipeline, "load_settings", lambda: settings)

    return use


def test_demo_seed_gives_the_same_decision_the_same_code(
    world, world_template, tmp_path, eligible_id, demo_seed
):
    import shutil

    from offer_engine.db import connect

    demo_seed(7)
    first = offer_row(world, pipeline.decide(world, eligible_id, CART, NOW).offer_id)["code"]
    shutil.copy(world_template, tmp_path / "again.db")
    again = connect(tmp_path / "again.db")
    second = offer_row(again, pipeline.decide(again, eligible_id, CART, NOW).offer_id)["code"]
    again.close()
    assert first == second and re.fullmatch(r"POE-[A-Z0-9]{6}", first)
    assert pipeline.new_code(eligible_id, NOW + timedelta(hours=1)) != first
    demo_seed(8)
    assert pipeline.new_code(eligible_id, NOW) != first


def test_a_taken_demo_code_moves_to_the_next_attempt(world, eligible_id, demo_seed):
    demo_seed(7)
    d1 = pipeline.decide(world, eligible_id, CART, NOW)
    d2 = pipeline.decide(world, eligible_id, CART, NOW, validate=False)
    codes = [offer_row(world, d.offer_id)["code"] for d in (d1, d2)]
    assert codes == [pipeline.new_code(eligible_id, NOW), pipeline.new_code(eligible_id, NOW, 1)]


def test_without_demo_seed_codes_are_random(eligible_id, demo_seed):
    demo_seed(None)
    assert len({pipeline.new_code(eligible_id, NOW) for _ in range(20)}) > 1
