"""Demo scenarios: the runner, seeded outcomes, setup and restore, and the CLI (T37); the tampered agent, the Rule
change and the withdraw (T38). Runs on the 50-Customer world with stand-in scenarios for its Customers, a fake offer
agent and a fake Customer Bot agent."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from types import SimpleNamespace

import pytest

from offer_engine import clock, pipeline, rules_store, withdraw
from offer_engine.choosers import rules_chooser
from offer_engine.cli import main
from offer_engine.customer_sim import roleplay
from offer_engine.db import connect
from offer_engine.demo import output, runner, scenarios, snapshot, tamper
from offer_engine.demo.scenarios import Expect, Scenario, forget_not_nows, restart, stop, three_not_nows
from offer_engine.domain import Chooser, OfferType, ParamRange, Proposal, RuleSet, TriggerKind
from offer_engine.personas import PersonaCard, path_for
from offer_engine.rules import in_holdout
from offer_engine.trace import STAGES

# What the rules chooser does for these 50-world Customers at 2026-12-01 00:00 (checked by the stand-ins' expects).
BOT, NO_CHAT, HOLDOUT, STOPS, PAUSED = "C00003", "C00004", "C00006", "C00007", "C00005"
CHATS = {BOT: 9001, STOPS: 9002}
SWEEP = TriggerKind.DAILY_SWEEP


def standins() -> list[Scenario]:
    def scenario(name, customer_id, expect, setup=None, restore=None, trigger=SWEEP):
        return Scenario(name, name, "a test", customer_id, setup, trigger, expect, "Test", restore)

    return [
        scenario(
            "bot-offer", BOT, Expect(OfferType.PCT_CATEGORY, Chooser.AGENT, "max_pct_by_loyalty_tier", True)
        ),
        scenario("no-chat-offer", NO_CHAT, Expect(OfferType.FREE_SHIPPING, Chooser.RULES)),
        scenario(
            "holdout", HOLDOUT, Expect(None, Chooser.RULES, "holdout_pct"), trigger=TriggerKind.CART_ABANDONED
        ),
        scenario("opted-out", STOPS, Expect(None, Chooser.RULES, "opt_out"), stop(STOPS), restart(STOPS)),
        scenario(
            "fatigue-pause",
            PAUSED,
            Expect(None, Chooser.RULES, "fatigue_dismissals"),
            three_not_nows(PAUSED),
            forget_not_nows(PAUSED),
        ),
    ]


class FakeRoleplay:
    """The Customer Bot's role-play agent: one fixed fit and pair of replies."""

    def __init__(self):
        self.calls = 0
        self.messages = self

    def create(self, **kwargs):
        self.calls += 1
        block = SimpleNamespace(
            type="tool_use",
            name=roleplay.TOOL_NAME,
            input={"fit": 0.5, "reply_claim": "Taking it!", "reply_not_now": "Maybe later."},
        )
        return SimpleNamespace(stop_reason="tool_use", content=[block])


def fake_agent(es, state, catalog, rules):
    """Proposes what the rules chooser would; the pipeline counts it as the agent."""
    return rules_chooser.choose(es, state, catalog, rules)


@pytest.fixture
def demo_world(world, monkeypatch, tmp_path):
    """The 50-Customer world with two Customer Bot chats, the stand-in scenarios, a fake offer agent for chat
    Customers and a fake role-play agent with a Persona Card for the bot Customer."""
    for customer_id, chat_id in CHATS.items():
        world.execute(
            "INSERT INTO chats (customer_id, chat_id, kind) VALUES (?, ?, 'bot')", (customer_id, chat_id)
        )
    world.commit()
    monkeypatch.setattr(scenarios, "SCENARIOS", standins())
    card = PersonaCard(BOT, "persuadable", "Meera Iyer", "Meera loves kurtas.", True, "", 7, 50)
    path_for(BOT, tmp_path).write_text(json.dumps(card.__dict__))
    monkeypatch.setattr(runner, "PERSONAS_DIR", tmp_path)
    fake = FakeRoleplay()
    monkeypatch.setattr(runner, "roleplay_agent", lambda: (fake, "fast-model"))
    with pipeline.chooser_override(lambda s, t: rules_chooser.choose if s.chat is None else fake_agent):
        yield world


def summary(result: runner.ScenarioResult) -> tuple:
    d = result.decision
    return (
        result.scenario.name,
        d.chooser,
        d.binding_rule,
        result.offer.get("offer_type"),
        result.offer.get("code"),
        result.p_base,
        result.fit,
        result.p_used,
        result.buys,
        result.claims,
        result.reply,
        result.passed,
    )


def copy_of(world, tmp_path, name: str):
    """A second connection on a copy of the world as it is now."""
    world.commit()
    world.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    path = tmp_path / f"{name}.db"
    shutil.copy(world.execute("PRAGMA database_list").fetchone()[2], path)
    return connect(path)


def test_the_fixture_customers_are_what_the_standins_assume(world):
    assert in_holdout(HOLDOUT, 10) and not any(in_holdout(c, 10) for c in (BOT, NO_CHAT, STOPS, PAUSED))


def test_every_standin_passes(demo_world):
    results = [runner.run(demo_world, s.name) for s in scenarios.SCENARIOS]
    assert [(r.scenario.name, r.mismatches) for r in results] == [(s.name, ()) for s in scenarios.SCENARIOS]


def test_the_runner_calls_on_stage_per_stage_in_order(demo_world):
    heard = []
    result = runner.run(demo_world, "bot-offer", on_stage=heard.append)
    assert heard == result.trace.stages
    assert [s.name for s in heard] == [n for n in STAGES if n != "fallback"]


def test_a_customer_bot_offer_is_settled_with_the_nudged_chance(demo_world):
    result = runner.run(demo_world, "bot-offer", seed=3)
    assert result.fit == 0.5
    assert result.p_used == pytest.approx(roleplay.nudged_chance(result.p_base, 0.5))
    assert result.reply.endswith(("/claim " + result.offer["code"], "/notnow " + result.offer["code"]))
    status = demo_world.execute(
        "SELECT status FROM offers WHERE id = ?", (result.decision.offer_id,)
    ).fetchone()[0]
    assert status == ("claimed" if result.claims else "dismissed")


def test_an_offer_without_a_chat_gets_the_ground_truth_draw(demo_world):
    result = runner.run(demo_world, "no-chat-offer")
    assert result.fit is None and result.reply is None
    assert result.p_used == result.p_base and 0 < result.p_base < 1
    fate = demo_world.execute(
        "SELECT buys, source FROM sim_offer_fates WHERE offer_id = ?", (result.decision.offer_id,)
    ).fetchone()
    assert (bool(fate[0]), fate[1]) == (result.buys, "ground_truth")


def test_no_offer_has_no_outcome(demo_world):
    result = runner.run(demo_world, "holdout")
    assert (result.p_base, result.buys, result.claims, result.reply) == (None, None, None, None)


def test_the_same_seed_gives_the_same_outcome_twice(demo_world, tmp_path):
    other = copy_of(demo_world, tmp_path, "other")
    try:
        first = runner.run(demo_world, "bot-offer", seed=11)
        second = runner.run(other, "bot-offer", seed=11)
    finally:
        other.close()
    assert summary(first) == summary(second)


def test_a_rerun_clears_the_earlier_run_and_matches_it(demo_world):
    first = runner.run(demo_world, "bot-offer")
    second = runner.run(demo_world, "bot-offer")
    assert summary(first) == summary(second)
    count = demo_world.execute("SELECT COUNT(*) FROM decisions WHERE customer_id = ?", (BOT,)).fetchone()[0]
    assert count == 1


def table(conn, sql: str) -> list[tuple]:
    return [tuple(row) for row in conn.execute(sql)]


def test_setup_and_restore_leave_the_rules_and_other_customers_unchanged(demo_world):
    rules = table(demo_world, "SELECT * FROM rule_versions")
    customers = table(demo_world, "SELECT * FROM customers ORDER BY id")
    others = f"customer_id NOT IN ('{STOPS}', '{PAUSED}')"
    offers = table(demo_world, f"SELECT * FROM offers WHERE {others} ORDER BY id")
    events = table(demo_world, f"SELECT * FROM events WHERE {others} ORDER BY id")
    paused_offers = table(demo_world, f"SELECT * FROM offers WHERE customer_id = '{PAUSED}' ORDER BY id")

    for name in ("opted-out", "fatigue-pause"):
        assert runner.run(demo_world, name).passed

    assert table(demo_world, "SELECT * FROM rule_versions") == rules
    assert table(demo_world, "SELECT * FROM customers ORDER BY id") == customers  # opted back in
    assert table(demo_world, f"SELECT * FROM offers WHERE {others} ORDER BY id") == offers
    assert table(demo_world, f"SELECT * FROM events WHERE {others} ORDER BY id") == events
    assert (
        table(demo_world, f"SELECT * FROM offers WHERE customer_id = '{PAUSED}' ORDER BY id") == paused_offers
    )


def test_two_scenarios_give_the_same_results_in_either_order(demo_world, tmp_path):
    other = copy_of(demo_world, tmp_path, "other")
    names = ["fatigue-pause", "opted-out", "bot-offer", "no-chat-offer"]
    try:
        forward = {n: summary(runner.run(demo_world, n)) for n in names}
        backward = {n: summary(runner.run(other, n)) for n in reversed(names)}
    finally:
        other.close()
    assert forward == backward


def test_a_wrong_expectation_fails_and_says_why(demo_world, monkeypatch):
    wrong = Scenario("wrong", "wrong", "a test", HOLDOUT, None, SWEEP, Expect(OfferType.NUDGE), "Test")
    monkeypatch.setattr(scenarios, "SCENARIOS", [wrong])
    result = runner.run(demo_world, "wrong")
    assert not result.passed
    assert result.mismatches == ("expected nudge, got No Offer",)
    assert output.verdict(result) == "FAIL wrong: expected nudge, got No Offer"


def test_output_shows_the_trace_decision_and_outcome(demo_world):
    text = "\n".join(output.result_lines(runner.run(demo_world, "bot-offer")))
    for title in ("Trigger", "Checks", "Eligible Set", "Valuation", "Agent", "Validation", "Offer"):
        assert f"\n{title}\n" in text
    assert "Decision: POE-" in text
    assert "message fit +0.50" in text
    assert text.endswith("PASS bot-offer")


def test_check_runs_each_scenario_on_a_fresh_copy_of_the_snapshot(demo_world, tmp_path):
    snap = tmp_path / "snap" / "demo.db"
    snapshot.snapshot(demo_world, snap)
    results = runner.check(snap)
    assert [r.scenario.name for r in results] == [s.name for s in scenarios.SCENARIOS]
    assert all(r.passed for r in results)
    assert list(snap.parent.iterdir()) == [snap]  # the copies are gone
    # Nothing was written to the snapshot itself.
    conn = connect(snap)
    assert conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 0
    conn.close()


def test_check_without_a_snapshot_says_how_to_make_one(tmp_path):
    with pytest.raises(FileNotFoundError, match="demo snapshot"):
        runner.check(tmp_path / "missing.db")


# --- The CLI -------------------------------------------------------------------------------------


@pytest.fixture
def cli_world(demo_world, monkeypatch):
    path = demo_world.execute("PRAGMA database_list").fetchone()[2]
    demo_world.commit()
    monkeypatch.setenv("DB_PATH", path)
    return path


def test_demo_list_prints_every_scenario_by_group(cli_world, capsys):
    assert main(["demo", "list"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Test:\n")
    assert all(f"  {s.name}" in out for s in scenarios.SCENARIOS)


def test_demo_run_prints_the_result_and_exits_1_on_fail(cli_world, capsys, monkeypatch):
    assert main(["demo", "run", "holdout"]) == 0
    assert capsys.readouterr().out.rstrip().endswith("PASS holdout")
    wrong = Scenario("wrong", "wrong", "a test", HOLDOUT, None, SWEEP, Expect(OfferType.NUDGE), "Test")
    monkeypatch.setattr(scenarios, "SCENARIOS", [wrong])
    assert main(["demo", "run", "wrong"]) == 1


def test_demo_run_refuses_an_unknown_scenario(cli_world):
    with pytest.raises(SystemExit, match="no scenario 'nope'"):
        main(["demo", "run", "nope"])


def test_demo_check_prints_pass_or_fail_per_scenario(demo_world, tmp_path, capsys, monkeypatch):
    snap = tmp_path / "snap.db"
    snapshot.snapshot(demo_world, snap)
    wrong = Scenario("wrong", "wrong", "a test", HOLDOUT, None, SWEEP, Expect(OfferType.NUDGE), "Test")
    monkeypatch.setattr(scenarios, "SCENARIOS", [*standins()[2:3], wrong])
    assert main(["demo", "check", "--path", str(snap)]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("PASS holdout · ")
    assert lines[1].startswith("FAIL wrong: expected nudge, got No Offer · ")
    assert lines[2] == "1 of 2 scenarios passed"


# --- T38: the safety net and marketer controls ---------------------------------------------------


def standin(name, customer_id, expect, **steps) -> Scenario:
    return Scenario(
        name, name, "a test", customer_id, steps.pop("setup", None), SWEEP, expect, "Test", **steps
    )


def run_one(conn, monkeypatch, scenario: Scenario) -> runner.ScenarioResult:
    monkeypatch.setattr(scenarios, "SCENARIOS", [scenario])
    return runner.run(conn, scenario.name)


TAMPER_40 = scenarios.tamper(
    offer_type=OfferType.PCT_CATEGORY, params={"pct": 40.0}, caption="40% off, just for you."
)


def test_the_t38_scenarios_follow_t37s_six():
    names = [s.name for s in scenarios.SCENARIOS]
    assert names[6:] == ["agent-breaks-rule", "manipulative-caption", "rule-change", "withdraw"]
    assert len(names) == len(set(names)) == 10


def test_a_tampered_40pct_proposal_is_rejected_and_the_fallback_offer_passes(demo_world, monkeypatch):
    expect = Expect(
        OfferType.PCT_CATEGORY, Chooser.FALLBACK, validation_ok=True, failure="param_out_of_range: pct=40"
    )
    result = run_one(demo_world, monkeypatch, standin("breaks", BOT, expect, wrap_chooser=TAMPER_40))
    assert result.passed, result.mismatches
    failure = next(f for f in result.decision.validation.failures if f.startswith("param_out_of_range"))
    assert failure.endswith("(max_pct_by_loyalty_tier)")
    tier = demo_world.execute("SELECT loyalty_tier FROM customers WHERE id = ?", (BOT,)).fetchone()[0]
    assert 0 < result.offer["params"]["pct"] <= RuleSet().max_pct_by_loyalty_tier[tier]
    stages = {s.name: s for s in result.trace.stages}
    assert "fallback" in stages and not stages["validation"].data["ok"]


def test_a_tamper_moves_any_answer_onto_the_option_and_marks_the_agent_output():
    option = SimpleNamespace(
        offer_type=OfferType.PCT_CATEGORY, category="beauty", ranges={"pct": ParamRange(5, 30)}
    )
    nudge = SimpleNamespace(offer_type=OfferType.NUDGE, category=None, ranges={})
    eligible = SimpleNamespace(options=(nudge, option), send_window=(datetime(2026, 12, 1, 9), None))

    class Agent:
        def __init__(self):
            self.last_output = {"option_index": 0, "params": {}, "caption": "Still there?"}

        def __call__(self, *args):
            return Proposal(OfferType.NUDGE, caption="Still there?", featured_product_ids=("G1",), reason="r")

    chooser = tamper.tampered(Agent(), offer_type=OfferType.PCT_CATEGORY, params={"pct": 40.0})
    proposal = chooser(eligible, None, None, None)
    assert (proposal.offer_type, proposal.category, proposal.params) == (
        OfferType.PCT_CATEGORY,
        "beauty",
        {"pct": 40},
    )
    assert proposal.featured_product_ids == () and proposal.caption == "Still there?"
    assert chooser.last_output["option_index"] == 1
    assert chooser.last_output["tampered"] == {"option_index": 1, "params": {"pct": 40.0}}


def test_the_tampered_caption_fails_the_caption_check(demo_world, monkeypatch):
    caption = scenarios.MANIPULATIVE_CAPTION
    expect = Expect(OfferType.PCT_CATEGORY, Chooser.FALLBACK, validation_ok=True, failure="invented_urgency")
    scenario = standin("caption", BOT, expect, wrap_chooser=scenarios.tamper(caption=caption))
    result = run_one(demo_world, monkeypatch, scenario)
    assert result.passed, result.mismatches
    stage = next(s for s in result.trace.stages if s.name == "validation")
    assert stage.data["caption_check"]["status"] == "failed"
    assert result.offer["caption"] != caption


def test_a_tamper_leaves_the_rules_chooser_and_later_decisions_alone(demo_world, monkeypatch):
    assert tamper.tampered(rules_chooser.choose, params={"pct": 40.0}) is rules_chooser.choose
    no_chat = run_one(
        demo_world, monkeypatch, standin("no-chat", NO_CHAT, Expect(None), wrap_chooser=TAMPER_40)
    )
    assert no_chat.decision.chooser == Chooser.RULES and no_chat.decision.validation.ok
    run_one(demo_world, monkeypatch, standin("breaks", BOT, Expect(None), wrap_chooser=TAMPER_40))
    runner.clear_run(demo_world, BOT, clock.now(demo_world))
    after = pipeline.decide(demo_world, BOT, SWEEP, clock.now(demo_world))
    assert after.chooser == Chooser.AGENT and after.validation.ok


def test_a_wrong_failure_expectation_says_what_failed(demo_world, monkeypatch):
    result = run_one(
        demo_world, monkeypatch, standin("plain", NO_CHAT, Expect(None, failure="invented_urgency"))
    )
    assert "expected a Validation failure 'invented_urgency', got none" in result.mismatches


def test_rule_change_shows_both_decisions_and_the_preview_then_reverts(demo_world, monkeypatch):
    tier = demo_world.execute("SELECT loyalty_tier FROM customers WHERE id = ?", (BOT,)).fetchone()[0]
    original = rules_store.current_rules(demo_world)
    setup, restore = scenarios.rule_change(BOT, scenarios.lower_tier_max(tier, 5.0), f"{tier} maximum to 5%")
    expect = Expect(OfferType.PCT_CATEGORY, binding_rule="max_pct_by_loyalty_tier", validation_ok=True)
    result = run_one(demo_world, monkeypatch, standin("change", BOT, expect, setup=setup, restore=restore))
    assert result.passed, result.mismatches
    assert result.offer["params"]["pct"] == 5
    before, preview_line, saved, reverted = result.lines
    assert before.startswith(f"Before, under Rules v{original[0]}: pct_category") and "pct=5 " not in before
    assert saved == f"Saved Rules v{original[0] + 1} as demo: {tier} maximum to 5%"
    assert preview_line.startswith("Preview impact on the next Daily Sweep (01 Dec 10:00): ")
    assert reverted == f"Reverted: Rules v{original[0] + 2}, saved as demo, equals v{original[0]}"
    # The Rules are back to their original content, in a new version.
    assert rules_store.current_rules(demo_world) == (original[0] + 2, original[1])
    assert [v.author for v in rules_store.list_versions(demo_world)[:2]] == ["demo", "demo"]
    # Only the scenario's own Decision is left: the one before the change was forgotten.
    assert (
        demo_world.execute("SELECT COUNT(*) FROM decisions WHERE customer_id = ?", (BOT,)).fetchone()[0] == 1
    )


def test_withdraw_marks_only_its_own_offers_withdrawn(demo_world, monkeypatch):
    others = f"SELECT * FROM offers WHERE customer_id != '{NO_CHAT}' ORDER BY id"
    before = table(demo_world, others)
    expect = Expect(None, Chooser.RULES, "frequency_cap_count")
    scenario = standin(
        "pull", NO_CHAT, expect, setup=scenarios.queue_offers(NO_CHAT), after=scenarios.withdraw_all(NO_CHAT)
    )
    for _ in range(2):  # a rerun replaces the first run's Offers
        result = run_one(demo_world, monkeypatch, scenario)
        assert result.passed, result.mismatches
    assert table(demo_world, others) == before
    own = table(
        demo_world,
        f"SELECT code, status FROM offers WHERE customer_id = '{NO_CHAT}' AND caption LIKE 'demo:%'",
    )
    assert own == [(f"DEMO-{NO_CHAT}-W1", "withdrawn"), (f"DEMO-{NO_CHAT}-W2", "withdrawn")]
    assert result.lines == (
        f"Queued 2 Offers for {NO_CHAT}: DEMO-{NO_CHAT}-W1 free_shipping, DEMO-{NO_CHAT}-W2 nudge",
        "Emergency withdraw by demo: 2 outstanding Offers withdrawn",
        f"  DEMO-{NO_CHAT}-W1: withdrawn",
        f"  DEMO-{NO_CHAT}-W2: withdrawn",
    )
    assert withdraw.list_withdrawals(demo_world)[0].author == "demo"


def test_output_prints_the_scenarios_lines_before_the_verdict(demo_world, monkeypatch):
    result = run_one(
        demo_world, monkeypatch, standin("say", NO_CHAT, Expect(None), setup=scenarios.say("Hello."))
    )
    assert output.result_lines(result, trace=False)[-2:] == ["Hello.", output.verdict(result)]
