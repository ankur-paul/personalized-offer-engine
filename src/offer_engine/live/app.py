"""The live engine view's server (T39, PLAN "Assumed › Code layout", QnA Q44, Q51, Q53).

A scenario runs in a worker thread and hands each trace stage to its run as the pipeline makes it; the page reads
the run's stages as Server-Sent Events and animates them. Stored traces of recent Decisions play back the same way.
The page shows what the trace says and nothing more. Like `commands` and `console` this is an entry point, but it
reads no Ground Truth: the truth panel is T40's.
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
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from offer_engine.commands._format import fetch_decisions, offer_terms
from offer_engine.config import load_settings
from offer_engine.db import connect
from offer_engine.demo import runner, scenarios
from offer_engine.trace import Stage, Trace

STATIC_DIR = Path(__file__).resolve().parent / "static"
GLOSSARY_PATH = Path(__file__).resolve().parents[3] / "GLOSSARY.md"
STATIC_TYPES = {"app.js": "text/javascript", "style.css": "text/css"}
LATEST_LIMIT = 20
# Finished runs kept for a late or repeated stream; older ones are forgotten.
RUNS_KEPT = 20
# Seconds between SSE comments while a stage takes long (the agent's call), so proxies keep the stream open.
KEEPALIVE = 15.0
TIME_FORMAT = "%Y-%m-%d %H:%M"

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
    """What the page shows after the stages: the scenario's check and what its steps reported. The outcome, which
    reads Ground Truth, is T40's."""
    return {
        "scenario": result.scenario.name,
        "decision_id": result.decision.id,
        "passed": result.passed,
        "mismatches": list(result.mismatches),
        "lines": list(result.lines),
    }


def create_app(
    db_path: Path | str | None = None,
    password: str | None = None,
    run_scenario: RunScenario = runner.run,
    glossary_path: Path = GLOSSARY_PATH,
) -> FastAPI:
    """The app on the database at `db_path` (default `DB_PATH`). With a `password`, every route asks for it by
    HTTP basic auth. `run_scenario` is `runner.run` but for tests."""
    db_path = load_settings().db_path if db_path is None else db_path
    glossary = read_glossary(glossary_path)
    runs: OrderedDict[str, Run] = OrderedDict()
    ids = itertools.count(1)
    busy = threading.Lock()

    app = FastAPI(title="Offer Engine live view", dependencies=[Depends(_auth(password))])

    def work(run: Run, name: str) -> None:
        conn = connect(db_path)
        try:
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
        threading.Thread(target=work, args=(run, name), name=f"scenario-{name}", daemon=True).start()
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
        with closing(connect(db_path)) as conn:
            return latest_decisions(conn)

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

    return app


def latest_decisions(conn: sqlite3.Connection, limit: int = LATEST_LIMIT) -> list[dict[str, Any]]:
    """The newest Decisions with their Offer terms, and whether each has a trace to play."""
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
            "trigger": r["trigger"],
            "offer": offer_terms(r),
            "traced": r["id"] in traced,
        }
        for r in rows
    ]


def _auth(password: str | None) -> Callable[..., None]:
    def check(credentials: Credentials) -> None:
        if not password:
            return
        if credentials is None or not hmac.compare_digest(credentials.password.encode(), password.encode()):
            raise HTTPException(
                401, "Wrong password", headers={"WWW-Authenticate": 'Basic realm="Offer Engine"'}
            )

    return check
