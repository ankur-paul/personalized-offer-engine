"""The live engine view's server (T39, PLAN "Assumed › Code layout", QnA Q44, Q51, Q53).

A scenario runs in a worker thread and hands each trace stage to its run as the pipeline makes it; the page reads
the run's stages as Server-Sent Events and animates them. Stored traces of recent Decisions play back the same way.
The page shows what the trace says and nothing more, except below the Offer stage (T40): the scenario's seeded
outcome and a truth panel marked "Hidden from the engine", and below that the world charts (T41). Like `commands` and `console` this is an entry point, so
it may read Ground Truth through `sim.explain`; the pipeline and the trace still never do.
"""

from __future__ import annotations

import hmac
import itertools
import json
import re
import sqlite3
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import closing, nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Body, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from offer_engine import clock, config, personas
from offer_engine.commands._format import fetch_decisions, offer_terms
from offer_engine.config import load_settings
from offer_engine.db import connect
from offer_engine.demo import runner, scenarios, snapshot
from offer_engine.domain import OfferType
from offer_engine.offer_bot.delivery import offer_from_row
from offer_engine.offer_card import render_offer_card
from offer_engine.rules_store import current_rules
from offer_engine.sim import explain
from offer_engine.sim.world_stats import world_stats
from offer_engine.trace import Stage, Trace

STATIC_DIR = Path(__file__).resolve().parent / "static"
GLOSSARY_PATH = Path(__file__).resolve().parents[3] / "GLOSSARY.md"
STATIC_TYPES = {
    "app.js": "text/javascript",
    "style.css": "text/css",
    "world.js": "text/javascript",
    "world.css": "text/css",
}
LATEST_LIMIT = 20
# Finished runs kept for a late or repeated stream; older ones are forgotten.
RUNS_KEPT = 20
# Seconds between SSE comments while a stage takes long (the agent's call), so proxies keep the stream open.
KEEPALIVE = 15.0
TIME_FORMAT = "%Y-%m-%d %H:%M"
# A Tester's copy is `<id>-t<telegram user id>`; its name is the source Customer's.
_TESTER_SUFFIX = re.compile(r"-t\d+$")

# The modes the page's Agent switch offers; `record` stays a `.env` setting.
PageAgentMode = Literal["replay", "live"]

RunScenario = Callable[..., runner.ScenarioResult]
# The browser's basic-auth answer, or None when it sent none. At module level: FastAPI resolves the annotation by name.
Credentials = Annotated[
    HTTPBasicCredentials | None, Depends(HTTPBasic(auto_error=False, realm="Offer Engine"))
]

# `**Term**:` on its own line, then the definition's first line.
_GLOSSARY_ENTRY = re.compile(r"^\*\*(.+?)\*\*:[ \t]*\n(.+)$", re.MULTILINE)
# A sentence ends at a stop before a capital or the line's end, so "e.g. the" doesn't end one.
_FIRST_SENTENCE = re.compile(r"(.+?[.!?])(?:\s+[A-Z]|\s*$)")


@dataclass
class Run:
    """One scenario run's events, kept whole so a stream that connects late still gets every stage."""

    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    done: bool = False
    changed: threading.Condition = field(default_factory=threading.Condition)

    def push(self, kind: str, data: dict[str, Any], last: bool = False) -> None:
        with self.changed:
            self.events.append((kind, data))
            self.done = self.done or last
            self.changed.notify_all()

    def stream(self, keepalive: float = KEEPALIVE) -> Iterator[str]:
        sent = 0
        while True:
            with self.changed:
                self.changed.wait_for(
                    lambda sent=sent: len(self.events) > sent or self.done, timeout=keepalive
                )
                new, done = self.events[sent:], self.done
            for kind, data in new:
                yield f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            sent += len(new)
            if done and not new:
                return
            if not new:
                yield ": waiting\n\n"


def read_glossary(path: Path = GLOSSARY_PATH) -> list[dict[str, str]]:
    """Each term with the first sentence of its definition, in file order."""
    return [
        {"term": term, "definition": first_sentence(definition)}
        for term, definition in _GLOSSARY_ENTRY.findall(path.read_text(encoding="utf-8"))
    ]


def first_sentence(text: str) -> str:
    match = _FIRST_SENTENCE.match(text.strip())
    return match.group(1) if match else text.strip()


def stage_json(stage: Stage) -> dict[str, Any]:
    return {"name": stage.name, "title": stage.title, "summary": stage.summary, "data": stage.data}


def result_json(result: runner.ScenarioResult) -> dict[str, Any]:
    """What the page shows after the stages: the scenario's check, what its steps reported and, when an Offer went
    out, its seeded outcome (ADR 0004): the chance before and after the message-fit nudge, the flip, the Customer
    Bot's reply and the Offer Bot's answer."""
    outcome = None
    if result.p_used is not None:
        outcome = {
            "p_base": result.p_base,
            "fit": result.fit,
            "p_used": result.p_used,
            "buys": result.buys,
            "claims": result.claims,
            "reply": result.reply,
            "bot_reply": result.bot_reply,
        }
    return {
        "scenario": result.scenario.name,
        "decision_id": result.decision.id,
        "customer_id": result.decision.customer_id,
        "offer_id": result.decision.offer_id,
        "passed": result.passed,
        "mismatches": list(result.mismatches),
        "lines": list(result.lines),
        "outcome": outcome,
    }


def create_app(
    db_path: Path | str | None = None,
    password: str | None = None,
    run_scenario: RunScenario = runner.run,
    glossary_path: Path = GLOSSARY_PATH,
    snapshot_path: Path = snapshot.DEFAULT_PATH,
    personas_dir: Path = personas.PERSONAS_DIR,
) -> FastAPI:
    """The app on the database at `db_path` (default `DB_PATH`). With a `password`, every route asks for it by
    HTTP basic auth. `run_scenario` is `runner.run` but for tests. Reset restores the snapshot at `snapshot_path`.
    The ticker names Customers from the Persona Cards in `personas_dir`."""
    db_path = load_settings().db_path if db_path is None else db_path
    glossary = read_glossary(glossary_path)
    runs: OrderedDict[str, Run] = OrderedDict()
    ids = itertools.count(1)
    # Held by a scenario run or a Reset, so neither starts while the other writes.
    busy = threading.Lock()
    # The Agent switch's mode for this process's scenario runs; None follows `.env`.
    chosen_mode: str | None = None

    app = FastAPI(title="Offer Engine live view", dependencies=[Depends(_auth(password))])

    def agent_mode() -> str:
        return chosen_mode or ("replay" if load_settings().agent_mode == "replay" else "live")

    def work(run: Run, name: str, mode: str | None) -> None:
        conn = connect(db_path)
        try:
            # A ContextVar set in this worker thread, so the Offer Bot and Customer Bots keep `.env`'s mode.
            with config.agent_mode(mode) if mode else nullcontext():
                result = run_scenario(conn, name, on_stage=lambda stage: run.push("stage", stage_json(stage)))
            run.push("result", result_json(result), last=True)
        except Exception as e:  # noqa: BLE001 — the page shows the failure instead of waiting forever
            run.push("failure", {"message": f"{type(e).__name__}: {e}"}, last=True)
        finally:
            conn.close()
            busy.release()

    @app.get("/")
    def page() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    @app.get("/static/{name}")
    def static(name: str) -> FileResponse:
        if name not in STATIC_TYPES:
            raise HTTPException(404)
        return FileResponse(STATIC_DIR / name, media_type=STATIC_TYPES[name])

    @app.get("/scenarios")
    def list_scenarios() -> list[dict[str, str]]:
        return [
            {"name": s.name, "title": s.title, "proves": s.proves, "group": s.group}
            for s in scenarios.SCENARIOS
        ]

    @app.post("/scenarios/{name}/run")
    def start_run(name: str) -> dict[str, str]:
        if name not in {s.name for s in scenarios.SCENARIOS}:
            raise HTTPException(404, f"no scenario {name!r}")
        if not busy.acquire(blocking=False):
            raise HTTPException(409, "A scenario is running")
        run_id = str(next(ids))
        runs[run_id] = run = Run()
        while len(runs) > RUNS_KEPT:
            runs.popitem(last=False)
        threading.Thread(
            target=work, args=(run, name, chosen_mode), name=f"scenario-{name}", daemon=True
        ).start()
        return {"run_id": run_id}

    @app.get("/runs/{run_id}/events")
    def events(run_id: str) -> StreamingResponse:
        run = runs.get(run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        return StreamingResponse(
            run.stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/decisions/latest")
    def latest() -> list[dict[str, Any]]:
        names = {card.customer_id: card.name for card in personas.load_all(personas_dir)}
        with closing(connect(db_path)) as conn:
            return latest_decisions(conn, names)

    @app.get("/decisions/{decision_id}/trace")
    def trace(decision_id: int) -> list[dict[str, Any]]:
        with closing(connect(db_path)) as conn:
            row = conn.execute(
                "SELECT trace FROM decision_traces WHERE decision_id = ?", (decision_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(404, f"Decision {decision_id} has no trace")
        return [stage_json(s) for s in Trace.from_json(row[0]).stages]

    @app.get("/glossary")
    def get_glossary() -> list[dict[str, str]]:
        return glossary

    @app.get("/customers/{customer_id}/truth")
    def truth(customer_id: str, decision_id: int | None = None) -> dict[str, Any]:
        """Ground Truth for the Customer: at `decision_id`'s time with its Eligible Set and Offer, else now."""
        with closing(connect(db_path)) as conn:
            view = truth_view(conn, customer_id, decision_id)
        return truth_json(view)

    @app.get("/offers/{offer_id}/card.png")
    def card(offer_id: int) -> Response:
        with closing(connect(db_path)) as conn:
            row = conn.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
        if row is None:
            raise HTTPException(404, f"no Offer {offer_id}")
        # The card the Offer Bot sends: no catalog names, as `delivery` draws it.
        return Response(render_offer_card(offer_from_row(row), {}), media_type="image/png")

    @app.get("/counters")
    def get_counters() -> dict[str, Any]:
        with closing(connect(db_path)) as conn:
            return counters(conn, clock.now(conn))

    @app.get("/world")
    def get_world() -> dict[str, Any]:
        """What the world has done since the clock start, for the world charts."""
        with closing(connect(db_path)) as conn:
            return world_stats(conn, clock.now(conn), current_rules(conn)[1])

    @app.post("/reset")
    def reset() -> dict[str, str]:
        if not busy.acquire(blocking=False):
            raise HTTPException(409, "A scenario is running")
        try:
            with closing(connect(db_path)) as conn:
                snapshot.reset(conn, snapshot_path)
                return {"time": clock.now(conn).strftime(TIME_FORMAT)}
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from None
        finally:
            busy.release()

    @app.get("/agent-mode")
    def get_agent_mode() -> dict[str, Any]:
        return {"mode": agent_mode(), "live_ready": bool(load_settings().anthropic_api_key)}

    @app.post("/agent-mode")
    def set_agent_mode(mode: Annotated[PageAgentMode, Body(embed=True)]) -> dict[str, Any]:
        nonlocal chosen_mode
        has_key = bool(load_settings().anthropic_api_key)
        if mode == "live" and not has_key:
            raise HTTPException(400, "Live needs ANTHROPIC_API_KEY in .env")
        chosen_mode = mode
        return {"mode": mode, "live_ready": has_key}

    return app


def truth_view(conn: sqlite3.Connection, customer_id: str, decision_id: int | None) -> explain.TruthView:
    """The truth panel's view. For a Decision: at its time, over its trace's Eligible Set at the deepest terms each
    option allowed, with its Offer at its own terms."""
    at, offer, candidates = clock.now(conn), None, []
    if decision_id is not None:
        row = conn.execute(
            "SELECT d.at, d.offer_id, t.trace FROM decisions d LEFT JOIN decision_traces t ON t.decision_id = d.id "
            "WHERE d.id = ? AND d.customer_id = ?",
            (decision_id, customer_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"{customer_id} has no Decision {decision_id}")
        at = datetime.fromisoformat(row["at"])
        if row["offer_id"] is not None:
            offer = conn.execute("SELECT * FROM offers WHERE id = ?", (row["offer_id"],)).fetchone()
        if row["trace"] is not None:
            candidates = eligible_candidates(Trace.from_json(row["trace"]))
    view = explain.truth_for(conn, customer_id, offer, at, candidates)
    if view is None:
        raise HTTPException(404, f"{customer_id} has no Ground Truth")
    return view


def eligible_candidates(trace: Trace) -> list[explain.Candidate]:
    """Each Eligible Set option at the top of every range (the bottom when the range is open)."""
    stage = next((s for s in trace.stages if s.name == "eligible_set"), None)
    if stage is None:
        return []
    return [
        explain.Candidate(
            OfferType(o["offer_type"]),
            o["category"],
            {p: lo if hi is None else hi for p, (lo, hi) in o["ranges"].items()},
        )
        for o in stage.data["options"]
    ]


def truth_json(view: explain.TruthView) -> dict[str, Any]:
    return {
        "customer_id": view.customer_id,
        "response_class": view.response_class,
        "time": view.at.strftime(TIME_FORMAT),
        "no_offer": view.no_offer,
        "options": [
            {
                "offer_type": str(o.offer_type),
                "category": o.category,
                "depth": o.depth,
                "chance": o.chance,
                "lift": o.lift,
                "chosen": o.chosen,
            }
            for o in view.options
        ],
    }


def counters(conn: sqlite3.Connection, now: datetime) -> dict[str, Any]:
    """The simulated day so far, and the same since the clock start under `since_start` (QnA Q55)."""
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = _iso(day + timedelta(days=1))
    return {
        "time": now.strftime(TIME_FORMAT),
        **_tally(conn, _iso(day), end),
        "since_start": {"since": clock.START.strftime(TIME_FORMAT), **_tally(conn, _iso(clock.START), end)},
    }


def _tally(conn: sqlite3.Connection, start: str, end: str) -> dict[str, Any]:
    """Decisions by Trigger, Offers sent, Claims, Redemptions and what they cost, from `start` up to `end`."""
    span = (start, end)
    decisions = dict(
        conn.execute(
            "SELECT trigger, COUNT(*) FROM decisions WHERE at >= ? AND at < ? GROUP BY 1 ORDER BY 1", span
        ).fetchall()
    )
    sent = conn.execute("SELECT COUNT(*) FROM offers WHERE sent_at >= ? AND sent_at < ?", span).fetchone()[0]
    claims, redemptions, spend = conn.execute(
        "SELECT COUNT(*) FILTER (WHERE kind = 'offer_claimed'), COUNT(*) FILTER (WHERE kind = 'offer_redeemed'), "
        "COALESCE(SUM(amount) FILTER (WHERE kind = 'offer_redeemed'), 0) FROM events "
        "WHERE kind IN ('offer_claimed', 'offer_redeemed') AND at >= ? AND at < ?",
        span,
    ).fetchone()
    return {
        "decisions": decisions,
        "offers_sent": sent,
        "claims": claims,
        "redemptions": redemptions,
        "spend": round(spend, 2),
    }


def latest_decisions(
    conn: sqlite3.Connection, names: dict[str, str] | None = None, limit: int = LATEST_LIMIT
) -> list[dict[str, Any]]:
    """The newest Decisions with their Offer terms, the Customer's name from `names` (None without a Persona Card),
    and whether each has a trace to play."""
    names = names or {}
    rows = fetch_decisions(conn, last=limit)
    traced = {
        r[0]
        for r in conn.execute(
            f"SELECT decision_id FROM decision_traces WHERE decision_id IN ({','.join('?' * len(rows))})",
            [r["id"] for r in rows],
        )
    }
    return [
        {
            "id": r["id"],
            "time": datetime.fromisoformat(r["at"]).strftime(TIME_FORMAT),
            "customer": r["customer_id"],
            "customer_name": names.get(_TESTER_SUFFIX.sub("", r["customer_id"])),
            "trigger": r["trigger"],
            "offer": offer_terms(r),
            "offer_id": r["offer_id"],
            "traced": r["id"] in traced,
        }
        for r in rows
    ]


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="seconds")


def _auth(password: str | None) -> Callable[..., None]:
    def check(credentials: Credentials) -> None:
        if not password:
            return
        if credentials is None or not hmac.compare_digest(credentials.password.encode(), password.encode()):
            raise HTTPException(
                401, "Wrong password", headers={"WWW-Authenticate": 'Basic realm="Offer Engine"'}
            )

    return check
