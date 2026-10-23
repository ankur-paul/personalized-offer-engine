# T21 — Console: Simulation Clock controls and Decision log
**Status:** DONE
**Prereqs:** T17 · **Branch:** t21-console-clock

## Goal
A marketer opens the Streamlit console, advances the Simulation Clock (+1 hour, +1 day, auto mode) and reads the
Decision log with reasons and Binding Rules. M5 (PLAN §6, §2.4; ADR 0003).

## Scope / files
- `console/app.py`: Streamlit entry with `st.navigation` over `console/pages/`; sidebar shows the simulated
  date/time on every page; optional password gate when `CONSOLE_PASSWORD` is set (T29 relies on it).
- `console/pages/1_clock.py`: buttons **+1 hour**, **+1 day**; **Auto mode** toggle advancing 1 simulated day every
  N wall-clock seconds (slider 5–60); shows the last DayReport counts.
- `console/pages/2_decisions.py`: table of Decisions newest first: time, Customer, Trigger, Offer summary (type,
  category, params), chooser, reason, Binding Rule, rule version, Validation result and failures. Filters:
  Customer ID, Trigger, chooser, "hide No Offer" (on by default). Click a row → the Offer's caption and status.
- `console/data.py`: query helpers returning DataFrames (tested).
- `src/offer_engine/commands/start.py`: add the console (`streamlit run console/app.py`) to `PROCESSES`, after the
  Customer Bot simulator entry.

## Details
- The console imports `offer_engine.sim.world.day_step.advance` (entry points may import `sim`).
- Auto mode must not double-advance if a step is still running.
- Done as built: a lock in `console/data.py` lets one day-step run at a time per console process. A press or Auto tick while it's held does nothing and says so. Auto mode is a `st.fragment(run_every=N)` that advances only when N seconds have passed since its last step, because a full rerun also calls the fragment.
- Done as built: `console` is a package. `app.py` puts the repo root on `sys.path`, and pytest gets it from `pythonpath = ["."]` in `pyproject.toml`. `start` runs the console as `python -m streamlit run <repo>/console/app.py --server.headless true`.
- Done as built: `validation_text` moved out of `decision_summary` in `commands/_format.py`, so the CLI and the console word the Validation result the same way.
- Done as built: the Check ran with `streamlit run console/app.py` on a 2,000-Customer world, not `offer-engine start`, since that needs the bot tokens in `.env`. +1 day moved the sidebar to 12-02 and listed the counts. Auto mode moved one day in 10 s. The Decision log listed 108 Decisions with reasons and Binding Rules, and a row showed its caption and status.

## Tests
- `tests/console/test_data.py`: Decision query filters.
- `tests/console/test_pages.py`: `streamlit.testing.v1.AppTest` loads each page without errors on a fixture DB;
  pressing **+1 day** moves the clock 24 h.

## Check
`uv run offer-engine start` → open the console URL; **+1 day** → sidebar date moves, report shows counts;
Decisions page lists the day's Decisions with reasons and Binding Rules.

## Done when
- [x] Clock page advances by hour, day and auto mode
- [x] Decision log shows reason, chooser, Binding Rule, rule version and Validation result with filters
- [x] `offer-engine start` also starts the console
- [x] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [x] Committed: `T21: console clock controls and Decision log`
