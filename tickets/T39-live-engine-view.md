# T39 — Live engine view: animated pipeline
**Status:** DONE
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
  - `GET /glossary` returns each `GLOSSARY.md` term with the first sentence of its definition, read from the file
    at startup.
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
  - Below the diagram, the current stage's title, summary and details: the Eligible Set as a table with Binding
    Rules, the value per option as bars, the agent's caption and reason, the Validation checks ticking one by one.
  - Each stage stays on screen for at least 1 s. During the agent stage the page shows "Claude is thinking…"
    until the stage arrives.
  - Scenario buttons are grouped by `group`, with each scenario's `proves` line as its subtitle.
  - A "Latest Decisions" ticker refreshes every 2 s. Clicking a row plays its stored trace at the same pace.
  - Light and dark themes; works from 1280 px wide down to a 390 px phone.
  - Layout and visual rules: Details › Look and feel.
- `src/offer_engine/commands/start.py`: add `("live", [sys.executable, "-m", "offer_engine.live"])` to
  `PROCESSES`, after the console line.
- `console/app.py`: a sidebar link "Live engine view" to http://localhost:8502 (from `LIVE_URL`, default that).

## Details
- `live/` is an entry point, not a pipeline module (PLAN "Assumed (approved 2026-10-26)"). This ticket reads no
  Ground Truth: the truth panel is T40.
- The page shows what the trace says. It computes no reasons of its own.
- T38 adds four scenarios and `ScenarioResult.lines`, the lines a scenario's steps report (the Decision before a
  Rule change, the preview numbers, the withdraw count). Render them as described under Look and feel, and don't
  change `scenarios.py`.

### Look and feel (QnA Q53)
The viewer is a judge who hasn't read `GLOSSARY.md`. They should see at a glance what to look at, and be able to
read each stage without help.
- **Layout from 1024 px:** a left rail about 260 px wide holds the scenario buttons, and below them the Latest
  Decisions ticker, showing 5 rows with a "Show 20" toggle. The main column has the diagram across the top and one
  card below it for the current stage. Clicking a finished node shows that stage's card again. Leave room below
  the card for T40's outcome and truth panels and above the diagram for its counters strip.
- **Below 1024 px:** the scenario buttons become a row above the diagram that scrolls sideways. At 390 px the
  diagram runs top to bottom, and the page never scrolls sideways.
- **One thing moves at a time:** only the active node pulses. With `prefers-reduced-motion` nothing pulses and
  stages switch without transitions.
- **Plain words:** every Glossary term in a stage title or summary gets a dotted underline and a tooltip with its
  first sentence from `/glossary`, on hover and on keyboard focus. The text comes from the Glossary, so the page
  still adds no reasons of its own.
- **Scenario lines:** after the Offer stage, the card lists `ScenarioResult.lines` under "What the scenario did",
  one numbered row per line. Text before the first `: ` is bold. An indented line is a sub-item of the line above.
- **Numbers:** rupees as `₹1,23,456`, percentages to one decimal.
- **Colour:** tokens on `:root`, redefined for dark mode. One accent colour for the active node and the buttons,
  green for done, red for a stop or failure, grey for stages not reached. No other hues; T40's truth panel gets a
  tinted background, not a new colour. Each status also has a symbol (✓, ✕), so colour is never the only signal.
  Text meets WCAG AA contrast (4.5:1).
- **Type and spacing:** the system font stack; sizes 14, 16, 20 and 28 px; line height 1.5. Spacing in multiples
  of 8 px. Cards have a 1 px border and 8 px radius, with no heavy shadows.

- Done as built: the tests are in `tests/live_view/`, not `tests/live/`. `conftest.py` skips any test whose keywords include `live`, and the folder name is a keyword (FRICTION-LOG). They run on the 50-Customer world, as T37's scenario tests do; the repo has no 300-Customer fixture. `create_app` takes `run_scenario`, so a test can set `chooser_override` in the worker thread (a ContextVar doesn't cross threads). A run's failure streams as a `failure` event, since `error` is EventSource's own connection event. `LIVE_PORT` and `LIVE_URL` come from the process environment, not `.env`. The password prompt is tested, not tried in a browser.

## Tests
- `tests/live/test_app.py` with FastAPI's `TestClient` on the 300-Customer fixture with stand-in scenarios and a
  fake agent:
  - `/scenarios` lists them.
  - A run streams one `stage` event per trace stage in order, then `result`.
  - A second concurrent run gets `409`.
  - Routes need the password when `CONSOLE_PASSWORD` is set.
  - `/decisions/{id}/trace` returns the stored trace.
  - `/glossary` returns every term in `GLOSSARY.md`, each with a one-sentence definition.
- `tests/test_start.py`: `PROCESSES` includes `live`.

## Check
`uv run offer-engine demo reset && AGENT_MODE=replay uv run offer-engine start`, then open
http://localhost:8502. The page asks for the password if one is set. Click **A Sure Thing gets No Offer**: the
stages light up one by one, and the Valuation stage shows every option below zero, ending at No Offer. In the
console, press **+1 day**; new Decisions appear in the ticker, and clicking one plays its trace.

Then look at the page at 1280 px and 390 px, in both themes. Run **rule-change** and check that its lines appear
under "What the scenario did". Hover over "Eligible Set" and check that its definition appears.

## Done when
- [x] `offer-engine start` serves the live page on port 8502, behind the password when set
- [x] A scenario button animates its Decision stage by stage with explanations
- [x] A ticker row plays back a stored trace
- [x] The page follows Look and feel at 1280 px and 390 px, in both themes
- [x] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [x] Committed: `T39: live engine view`
