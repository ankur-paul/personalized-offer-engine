"""The live engine view's server (T39, T40): scenarios, the SSE stream of a run, one run at a time, the password, stored
traces, the latest Decisions, the Glossary, the outcome, the truth panel, the Offer Card, counters, Reset and the
Agent switch. Runs on the 50-Customer world with stand-in scenarios and a fake offer agent."""

from __future__ import annotations

import json
import re
import threading
from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from offer_engine import clock, config, personas, pipeline, testers
from offer_engine.choosers import rules_chooser
from offer_engine.db import load_catalog
from offer_engine.demo import runner, scenarios, snapshot
from offer_engine.demo.scenarios import Expect, Scenario
from offer_engine.domain import Chooser, OfferType, TriggerKind
from offer_engine.live import app as live_app
from offer_engine.live.app import Run, create_app, first_sentence, read_glossary
from offer_engine.personas import PersonaCard
from offer_engine.sim import ground_truth
from offer_engine.sim.world import outcomes

# What the rules chooser does for these 50-world Customers at 2026-12-01 00:00 (tests/demo/test_scenarios.py).
NO_CHAT, HOLDOUT = "C00004", "C00006"
GATE_TIMEOUT = 10.0


def standins(gate: threading.Event) -> list[Scenario]:
    def wait(conn, now):
        gate.wait(GATE_TIMEOUT)
        return ["Waited: for the test"]

    sweep = TriggerKind.DAILY_SWEEP
    return [
        Scenario("offer", "An Offer", "a test", NO_CHAT, None, sweep, Expect(OfferType.FREE_SHIPPING), "One"),
        Scenario(
            "holdout",
            "A Holdout",
            "a test",
            HOLDOUT,
            None,
            TriggerKind.CART_ABANDONED,
            Expect(None, Chooser.RULES, "holdout_pct"),
            "Two",
        ),
        Scenario("slow", "Waits", "a test", NO_CHAT, wait, sweep, Expect(OfferType.FREE_SHIPPING), "Two"),
    ]


def fake_agent(es, state, catalog, rules):
    return rules_chooser.choose(es, state, catalog, rules)


def run_with_fake_agent(conn, name, **kwargs):
    """`runner.run` with every Customer decided by a fake agent; the override is set in the worker's own thread."""
    with pipeline.chooser_override(lambda s, t: fake_agent):
        return runner.run(conn, name, **kwargs)


@pytest.fixture
def gate():
    event = threading.Event()
    yield event
    event.set()


@pytest.fixture
def db_path(world, monkeypatch, gate):
    monkeypatch.setattr(scenarios, "SCENARIOS", standins(gate))
    world.commit()
    return world.execute("PRAGMA database_list").fetchone()[2]


@pytest.fixture
def personas_dir(tmp_path):
    return tmp_path / "personas"


@pytest.fixture
def client(db_path, personas_dir):
    return TestClient(create_app(db_path, run_scenario=run_with_fake_agent, personas_dir=personas_dir))


def events(client: TestClient, run_id: str) -> list[tuple[str, dict]]:
    """Every event of a run's stream, read until it ends."""
    with client.stream("GET", f"/runs/{run_id}/events") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        text = "".join(response.iter_text())
    out = []
    for block in text.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith(":"))
        if fields:
            out.append((fields["event"], json.loads(fields["data"])))
    return out


def run(client: TestClient, name: str) -> list[tuple[str, dict]]:
    response = client.post(f"/scenarios/{name}/run")
    assert response.status_code == 200
    return events(client, response.json()["run_id"])


def test_scenarios_lists_name_title_proves_and_group(client):
    assert client.get("/scenarios").json() == [
        {"name": "offer", "title": "An Offer", "proves": "a test", "group": "One"},
        {"name": "holdout", "title": "A Holdout", "proves": "a test", "group": "Two"},
        {"name": "slow", "title": "Waits", "proves": "a test", "group": "Two"},
    ]


def test_a_run_streams_each_stage_in_order_then_the_result(client):
    got = run(client, "offer")
    kinds = [kind for kind, _ in got]
    assert kinds == ["stage"] * (len(got) - 1) + ["result"]
    result = got[-1][1]
    assert result["scenario"] == "offer" and result["passed"] and result["mismatches"] == []
    stored = client.get(f"/decisions/{result['decision_id']}/trace").json()
    assert [data for _, data in got[:-1]] == stored
    assert stored[0]["name"] == "trigger" and stored[-1]["name"] == "offer"
    assert stored[-1]["data"]["offer_type"] == "free_shipping"


def test_a_stopped_decision_streams_its_stop(client):
    got = run(client, "holdout")
    names = [data["name"] for kind, data in got if kind == "stage"]
    assert names == ["trigger", "customer", "checks", "offer"]
    checks = got[2][1]["data"]
    assert checks["stopped_by"] == "holdout" and got[-1][1]["passed"]


def test_a_stream_that_connects_late_gets_every_event_and_a_second_stream_too(client):
    run_id = client.post("/scenarios/offer/run").json()["run_id"]
    first = events(client, run_id)
    assert events(client, run_id) == first


def test_a_second_run_while_one_runs_gets_409(client, gate):
    run_id = client.post("/scenarios/slow/run").json()["run_id"]
    busy = client.post("/scenarios/offer/run")
    assert busy.status_code == 409 and busy.json()["detail"] == "A scenario is running"
    gate.set()
    assert events(client, run_id)[-1][1]["lines"] == ["Waited: for the test"]
    assert client.post("/scenarios/offer/run").status_code == 200


def test_an_unknown_scenario_or_run_is_404(client):
    assert client.post("/scenarios/nope/run").status_code == 404
    assert client.get("/runs/999/events").status_code == 404


def test_a_failing_run_streams_a_failure_and_frees_the_lock(db_path):
    def broken(conn, name, **kwargs):
        raise LookupError("C00004 has no chat")

    client = TestClient(create_app(db_path, run_scenario=broken))
    assert run(client, "offer") == [("failure", {"message": "LookupError: C00004 has no chat"})]
    assert client.post("/scenarios/offer/run").status_code == 200


@pytest.mark.parametrize("path", ["/", "/static/app.js", "/static/style.css", "/scenarios", "/glossary"])
def test_every_route_needs_the_password_when_set(db_path, path):
    client = TestClient(create_app(db_path, password="s3cret"))
    refused = client.get(path)
    assert refused.status_code == 401 and refused.headers["www-authenticate"].startswith("Basic")
    assert client.get(path, auth=("anyone", "wrong")).status_code == 401
    assert client.get(path, auth=("anyone", "s3cret")).status_code == 200


def test_no_password_means_no_prompt(client):
    assert client.get("/scenarios").status_code == 200


def test_the_page_and_its_files_are_served(client):
    page = client.get("/")
    assert page.headers["content-type"].startswith("text/html") and "/static/app.js" in page.text
    assert client.get("/static/app.js").headers["content-type"].startswith("text/javascript")
    assert client.get("/static/style.css").headers["content-type"].startswith("text/css")
    assert client.get("/static/index.html").status_code == 404


def test_a_decision_without_a_trace_is_404(client):
    assert client.get("/decisions/999999/trace").status_code == 404


def test_latest_lists_the_newest_decisions_first_with_their_offer(client):
    offer = run(client, "offer")[-1][1]["decision_id"]
    stopped = run(client, "holdout")[-1][1]["decision_id"]
    latest = client.get("/decisions/latest").json()
    assert len(latest) <= live_app.LATEST_LIMIT
    assert [d["id"] for d in latest[:2]] == [stopped, offer]
    assert latest[0] == {
        "id": stopped,
        "time": "2026-12-01 00:00",
        "customer": HOLDOUT,
        "customer_name": None,
        "trigger": "cart_abandoned",
        "offer": "No Offer",
        "offer_id": None,
        "traced": True,
    }
    assert latest[1]["offer"].startswith("free_shipping")


def test_latest_names_each_customer_with_a_persona_card(client, world, personas_dir):
    personas.save(
        PersonaCard(HOLDOUT, "regular", "Asha Verma", "A card.", True, "2026-10-26T00:00:00", 1, 50),
        personas_dir,
    )
    run(client, "offer")
    run(client, "holdout")
    named = lambda: [(d["customer"], d["customer_name"]) for d in client.get("/decisions/latest").json()]
    assert named() == [(HOLDOUT, "Asha Verma"), (NO_CHAT, None)]
    # A Tester's copy carries its source Customer's name.
    copy = testers.create_tester_copy(world, HOLDOUT, 42)
    world.execute("UPDATE decisions SET customer_id = ? WHERE id = (SELECT MAX(id) FROM decisions)", (copy,))
    world.commit()
    assert named()[0] == (copy, "Asha Verma")


def test_glossary_has_every_term_with_one_sentence(client):
    text = live_app.GLOSSARY_PATH.read_text()
    terms = re.findall(r"^\*\*(.+?)\*\*:\s*$", text, re.MULTILINE)
    glossary = client.get("/glossary").json()
    assert [g["term"] for g in glossary] == terms and len(terms) > 30
    for g in glossary:
        assert g["definition"].endswith(".") and not re.search(r"[.!?]\s+[A-Z]", g["definition"]), g


def test_first_sentence_skips_abbreviations():
    assert (
        first_sentence("The Rule, e.g. the margin floor. When Rules conflict.")
        == "The Rule, e.g. the margin floor."
    )
    assert first_sentence("No stop at all") == "No stop at all"


def test_read_glossary_reads_bold_terms(tmp_path):
    path = tmp_path / "GLOSSARY.md"
    path.write_text("# Title\n\n**Thing**:\nA thing. More.\n_Avoid_: stuff\n\n**Other**:\nAnother one.\n")
    assert read_glossary(path) == [
        {"term": "Thing", "definition": "A thing."},
        {"term": "Other", "definition": "Another one."},
    ]


def test_a_quiet_run_sends_keepalive_comments():
    run = Run()
    stream = run.stream(keepalive=0.01)
    assert next(stream) == ": waiting\n\n"
    run.push("result", {"ok": True}, last=True)
    assert next(stream) == 'event: result\ndata: {"ok": true}\n\n'
    assert list(stream) == []


# --- T40: outcome, truth panel, Offer Card, counters, Reset, Agent switch -----------------------------


@pytest.fixture
def settings(monkeypatch):
    """The settings the app reads, with no API key and `.env`'s agent mode ignored; set `.key` to give it one."""

    class Fake:
        key = None

        def __call__(self, env_file=None):
            return replace(config.Settings(), anthropic_api_key=self.key, agent_mode="live")

    fake = Fake()
    monkeypatch.setattr(live_app, "load_settings", fake)
    return fake


def test_a_run_with_an_offer_ends_with_its_seeded_outcome(client, world):
    result = run(client, "offer")[-1][1]
    out = result["outcome"]
    assert result["customer_id"] == NO_CHAT and result["offer_id"] is not None
    # No chat, so no Customer Bot: the plain Ground Truth draw, with no message fit and no reply.
    assert out["fit"] is None and out["reply"] is None and out["p_base"] == out["p_used"]
    assert 0 < out["p_used"] < 1 and isinstance(out["buys"], bool) and out["bot_reply"]


def test_a_stopped_run_has_no_outcome(client):
    result = run(client, "holdout")[-1][1]
    assert result["offer_id"] is None and result["outcome"] is None


def test_truth_without_a_decision_is_the_no_offer_chance_now(client, world):
    truth = client.get(f"/customers/{NO_CHAT}/truth").json()
    gt = ground_truth.load(world, NO_CHAT)[OfferType.NUDGE]
    assert truth["no_offer"] == pytest.approx(ground_truth.p_buy(gt, 0.0))
    assert truth["response_class"] == "lost_cause" and truth["options"] == []
    assert truth["time"] == "2026-12-01 00:00"


def test_truth_for_a_decision_prices_its_eligible_set_and_marks_the_offer(client, world):
    result = run(client, "offer")[-1][1]
    truth = client.get(f"/customers/{NO_CHAT}/truth", params={"decision_id": result["decision_id"]}).json()
    stage = client.get(f"/decisions/{result['decision_id']}/trace").json()[3]
    assert stage["name"] == "eligible_set"
    assert [(o["offer_type"], o["category"]) for o in truth["options"]] == [
        (o["offer_type"], o["category"]) for o in stage["data"]["options"]
    ]
    chosen = [o for o in truth["options"] if o["chosen"]]
    assert [o["offer_type"] for o in chosen] == ["free_shipping"]
    # The chance the outcome flipped on is the truth panel's chance for the Offer.
    assert chosen[0]["chance"] == pytest.approx(result["outcome"]["p_used"])
    offer = world.execute("SELECT * FROM offers WHERE id = ?", (result["offer_id"],)).fetchone()
    customer = outcomes.sim_customer(world, NO_CHAT)
    assert chosen[0]["chance"] == pytest.approx(
        outcomes.buy_chance(customer, offer, load_catalog(world), clock.START)
    )
    for o in truth["options"]:
        gt = ground_truth.load(world, NO_CHAT)[OfferType(o["offer_type"])]
        assert o["chance"] == pytest.approx(ground_truth.p_buy(gt, o["depth"]))


def test_truth_is_404_for_an_unknown_customer_or_someone_elses_decision(client):
    decision = run(client, "offer")[-1][1]["decision_id"]
    assert client.get("/customers/C99999/truth").status_code == 404
    assert client.get(f"/customers/{HOLDOUT}/truth", params={"decision_id": decision}).status_code == 404


def test_the_offer_card_is_a_png(client):
    offer_id = run(client, "offer")[-1][1]["offer_id"]
    card = client.get(f"/offers/{offer_id}/card.png")
    assert card.headers["content-type"] == "image/png" and card.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert client.get("/offers/999999/card.png").status_code == 404


def test_counters_count_the_simulated_day(client, world):
    day = clock.START + timedelta(hours=9)
    before, after = clock.START - timedelta(minutes=1), clock.START + timedelta(days=1)
    for at, trigger in [
        (day, "daily_sweep"),
        (day, "daily_sweep"),
        (day, "cart_abandoned"),
        (before, "lapse_risk"),
    ]:
        world.execute(
            "INSERT INTO decisions (customer_id, at, trigger, chooser, rule_version) VALUES ('C00001', ?, ?, 'rules', 0)",
            (at.isoformat(), trigger),
        )
    for i, at in enumerate([day, day, after]):
        world.execute(
            "INSERT INTO offers (code, customer_id, offer_type, params, created_at, send_at, sent_at, expires_at, "
            "rule_version, worst_case_cost, expected_cost, status, source) "
            "VALUES (?, 'C00001', 'nudge', '{}', ?, ?, ?, ?, 0, 0, 0, 'sent', 'live')",
            (f"POE-CNT00{i}", *[at.isoformat()] * 4),
        )
    for kind, amount, at in [
        ("offer_claimed", None, day),
        ("offer_claimed", None, day),
        ("offer_redeemed", 120.0, day),
        ("offer_redeemed", 80.5, day),
        ("offer_redeemed", 999.0, after),
    ]:
        world.execute(
            "INSERT INTO events (customer_id, at, kind, amount) VALUES ('C00001', ?, ?, ?)",
            (at.isoformat(), kind, amount),
        )
    clock.set_now(world, day + timedelta(hours=2))
    world.commit()
    today = {
        "decisions": {"cart_abandoned": 1, "daily_sweep": 2},
        "offers_sent": 2,
        "claims": 2,
        "redemptions": 2,
        "spend": 200.5,
    }
    assert client.get("/counters").json() == {
        "time": "2026-12-01 11:00",
        **today,
        "since_start": {"since": "2026-12-01 00:00", **today},
    }

    # The next day: today starts at 0, and the totals since the clock start keep the first day (QnA Q55).
    clock.set_now(world, after + timedelta(hours=1))
    world.commit()
    counts = client.get("/counters").json()
    assert (counts["decisions"], counts["offers_sent"], counts["redemptions"], counts["spend"]) == (
        {},
        1,
        1,
        999.0,
    )
    assert counts["since_start"] == {
        "since": "2026-12-01 00:00",
        "decisions": {"cart_abandoned": 1, "daily_sweep": 2},
        "offers_sent": 3,
        "claims": 2,
        "redemptions": 3,
        "spend": 1199.5,
    }


def test_world_returns_every_chart_section(client, world):
    world.execute(
        "INSERT INTO decisions (customer_id, at, trigger, chooser, rule_version) VALUES ('C00001', ?, 'daily_sweep', 'rules', 0)",
        ((clock.START + timedelta(hours=10)).isoformat(),),
    )
    world.commit()
    stats = client.get("/world").json()
    assert set(stats) == {"time", "since", "days", "funnel", "holdout", "truth", "choosers", "chats"}
    assert stats["days"][0]["groups"]["nothing"] == 1
    assert sum(r["customers"] for r in stats["truth"]) == 50


def test_the_world_module_files_are_served(client):
    assert "export function mountWorld" in client.get("/static/world.js").text
    assert client.get("/static/world.css").headers["content-type"].startswith("text/css")
    assert 'id="world"' in client.get("/").text


def test_reset_restores_the_snapshot(db_path, world, tmp_path):
    path = tmp_path / "demo.db"
    snapshot.snapshot(world, path)
    clock.advance(world, 30)
    world.commit()
    client = TestClient(create_app(db_path, run_scenario=run_with_fake_agent, snapshot_path=path))
    assert client.get("/counters").json()["time"] == "2026-12-02 06:00"
    assert client.post("/reset").json() == {"time": "2026-12-01 00:00"}
    assert client.get("/counters").json()["time"] == "2026-12-01 00:00"


def test_reset_while_a_scenario_runs_gets_409(db_path, world, tmp_path, gate):
    path = tmp_path / "demo.db"
    snapshot.snapshot(world, path)
    client = TestClient(create_app(db_path, run_scenario=run_with_fake_agent, snapshot_path=path))
    run_id = client.post("/scenarios/slow/run").json()["run_id"]
    busy = client.post("/reset")
    assert busy.status_code == 409 and busy.json()["detail"] == "A scenario is running"
    gate.set()
    events(client, run_id)
    assert client.post("/reset").status_code == 200


def test_reset_without_a_snapshot_is_404(db_path, tmp_path):
    client = TestClient(create_app(db_path, snapshot_path=tmp_path / "missing.db"))
    missing = client.post("/reset")
    assert missing.status_code == 404 and "demo snapshot" in missing.json()["detail"]


def test_the_agent_switch_sets_the_mode_for_scenario_runs_only(db_path, settings):
    seen = []

    def record_mode(conn, name, **kwargs):
        seen.append(config.load_settings().agent_mode)
        return run_with_fake_agent(conn, name, **kwargs)

    client = TestClient(create_app(db_path, run_scenario=record_mode))
    assert client.get("/agent-mode").json() == {"mode": "live", "live_ready": False}
    assert client.post("/agent-mode", json={"mode": "replay"}).json() == {
        "mode": "replay",
        "live_ready": False,
    }
    assert client.get("/agent-mode").json()["mode"] == "replay"
    run(client, "offer")
    assert seen == ["replay"]
    # The server's own thread, like the bots, keeps `.env`'s mode.
    assert config.load_settings().agent_mode == config.read_env().get("AGENT_MODE", "live").lower()


def test_live_needs_a_key_and_record_is_not_offered(client, settings):
    refused = client.post("/agent-mode", json={"mode": "live"})
    assert refused.status_code == 400 and "ANTHROPIC_API_KEY" in refused.json()["detail"]
    assert client.post("/agent-mode", json={"mode": "record"}).status_code == 422
    settings.key = "sk-test"
    assert client.post("/agent-mode", json={"mode": "live"}).json() == {"mode": "live", "live_ready": True}


def test_a_scenario_trace_holds_no_ground_truth(client, world):
    """ADR 0002: the trace is the pipeline's, so no Ground Truth field name appears in it."""
    result = run(client, "offer")[-1][1]
    text = json.dumps(client.get(f"/decisions/{result['decision_id']}/trace").json())
    columns = {
        row[1]
        for table in ("sim_ground_truth", "sim_response_class", "sim_customer_traits")
        for row in world.execute(f"PRAGMA table_info({table})")
    } - {"customer_id", "offer_type"}  # the keys, shared with the pipeline's own tables
    names = columns | {
        "response_class",
        "p_buy",
        "p_base",
        "p_used",
        "buy_chance",
        *ground_truth.RESPONSE_CLASSES,
    }
    found = {n for n in names if re.search(rf"\b{re.escape(n)}\b", text)}
    assert found == set()
