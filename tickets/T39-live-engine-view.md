# T39 — Live engine view: animated pipeline
**Status:** TODO
**Prereqs:** T37 · **Branch:** t39-live-engine-view

## Goal
A browser page that shows what the engine is doing right now and why. Click a scenario button and the pipeline
diagram lights up stage by stage, with a plain-English explanation at each stage. Click any recent Decision and its
stored trace plays back the same way. Part 3b of the demo pass: T37 → T38 / T39 → T40 (PLAN "Assumed (approved
2026-10-26) › Code layout", QnA Q44, Q51).

## Scope / files
- `pyproject.toml`: add `fastapi` and `uvicorn`. This is the only ticket in the pass that adds dependencies.
- `src/offer_engine/live/app.py`, the FastAPI app:
  - `GET /` serves the page.
  - `GET /scenarios` returns `SCENARIOS` (name, title, proves, group).
  - `POST /scenarios/{name}/run` runs the scenario in a worker thread with `on_stage` pushing each stage to an
    event queue, and returns a run ID.
  - `GET /runs/{id}/events` is the SSE stream: one `stage` event per stage, then `result`.
  - `GET /decisions/latest` returns the last 20 Decisions: ID, time, Customer, Trigger, Offer or No Offer.
  - `GET /decisions/{id}/trace` returns a stored trace.
  - When `CONSOLE_PASSWORD` is set, every route uses HTTP basic auth (any username, that password).
  - One scenario runs at a time. A second click while one runs gets `409` and the page says "A scenario is
    running".
- `src/offer_engine/live/__main__.py`: `python -m offer_engine.live` runs uvicorn on `0.0.0.0:8502` (port from
  env `LIVE_PORT`).
- `src/offer_engine/live/static/index.html`, `app.js`, `style.css`, with no build step:
  - An SVG pipeline diagram: Trigger → Customer → Checks → Eligible Set → Valuation → Agent → Validation →
    Fallback → Offer.
  - The active stage pulses. Done stages turn green, or red for a stop or failure. The Fallback node appears only
    when used.
  - Beside the diagram, the current stage's title, summary and details: the Eligible Set as a table with Binding
    Rules, the value per option as bars, the agent's caption and reason, the Validation checks ticking one by one.
  - Each stage stays on screen for at least 1 s. During the agent stage the page shows "Claude is thinking…"
    until the stage arrives.
  - Scenario buttons are grouped by `group`, with each scenario's `proves` line as its subtitle.
  - A "Latest Decisions" ticker refreshes every 2 s. Clicking a row plays its stored trace at the same pace.
  - Light and dark themes; works from 1280 px wide down to a 390 px phone.
- `src/offer_engine/commands/start.py`: add `("live", [sys.executable, "-m", "offer_engine.live"])` to
  `PROCESSES`, after the console line.
- `console/app.py`: a sidebar link "Live engine view" to http://localhost:8502 (from `LIVE_URL`, default that).

## Details
- `live/` is an entry point, not a pipeline module (PLAN "Assumed (approved 2026-10-26)"). This ticket reads no
  Ground Truth: the truth panel is T40.
- The page shows what the trace says. It computes no reasons of its own.
- T38 may append scenarios and an extra-lines field to `ScenarioResult` in parallel. Render that field generically
  as a list of lines if present, and don't change `scenarios.py`.

## Tests
- `tests/live/test_app.py` with FastAPI's `TestClient` on the 300-Customer fixture with stand-in scenarios and a
  fake agent:
  - `/scenarios` lists them.
  - A run streams one `stage` event per trace stage in order, then `result`.
  - A second concurrent run gets `409`.
  - Routes need the password when `CONSOLE_PASSWORD` is set.
  - `/decisions/{id}/trace` returns the stored trace.
- `tests/test_start.py`: `PROCESSES` includes `live`.

## Check
`uv run offer-engine demo reset && AGENT_MODE=replay uv run offer-engine start`, then open
http://localhost:8502. The page asks for the password if one is set. Click **A Sure Thing gets No Offer**: the
stages light up one by one, and the Valuation stage shows every option below zero, ending at No Offer. In the
console, press **+1 day**; new Decisions appear in the ticker, and clicking one plays its trace.

## Done when
- [ ] `offer-engine start` serves the live page on port 8502, behind the password when set
- [ ] A scenario button animates its Decision stage by stage with explanations
- [ ] A ticker row plays back a stored trace
- [ ] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [ ] Committed: `T39: live engine view`
