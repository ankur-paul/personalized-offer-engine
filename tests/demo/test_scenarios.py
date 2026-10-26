"""Demo scenarios: the runner, seeded outcomes, setup and restore, and the CLI (T37). Runs on the 50-Customer
world with stand-in scenarios for its Customers, a fake offer agent and a fake Customer Bot agent."""

from __future__ import annotations

import json
import shutil
from types import SimpleNamespace

import pytest

from offer_engine import pipeline
from offer_engine.choosers import rules_chooser
from offer_engine.cli import main
from offer_engine.customer_sim import roleplay
from offer_engine.db import connect
from offer_engine.demo import output, runner, scenarios, snapshot
from offer_engine.demo.scenarios import Expect, Scenario, forget_not_nows, restart, stop, three_not_nows
from offer_engine.domain import Chooser, OfferType, TriggerKind
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
