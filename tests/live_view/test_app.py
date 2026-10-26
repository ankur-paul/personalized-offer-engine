"""The live engine view's server (T39): scenarios, the SSE stream of a run, one run at a time, the password, stored
traces, the latest Decisions and the Glossary. Runs on the 50-Customer world with stand-in scenarios and a fake
offer agent."""

from __future__ import annotations

import json
import re
import threading

import pytest
from fastapi.testclient import TestClient

from offer_engine import pipeline
from offer_engine.choosers import rules_chooser
from offer_engine.demo import runner, scenarios
from offer_engine.demo.scenarios import Expect, Scenario
from offer_engine.domain import Chooser, OfferType, TriggerKind
from offer_engine.live import app as live_app
from offer_engine.live.app import Run, create_app, first_sentence, read_glossary

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
def client(db_path):
    return TestClient(create_app(db_path, run_scenario=run_with_fake_agent))


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
        "trigger": "cart_abandoned",
        "offer": "No Offer",
        "traced": True,
    }
    assert latest[1]["offer"].startswith("free_shipping")


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
