# T21 — Console: Simulation Clock controls and Decision log
**Status:** TODO
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

## Tests
- `tests/console/test_data.py`: Decision query filters.
- `tests/console/test_pages.py`: `streamlit.testing.v1.AppTest` loads each page without errors on a fixture DB;
  pressing **+1 day** moves the clock 24 h.

## Check
`uv run offer-engine start` → open the console URL; **+1 day** → sidebar date moves, report shows counts;
Decisions page lists the day's Decisions with reasons and Binding Rules.

## Done when
- [ ] Clock page advances by hour, day and auto mode
- [ ] Decision log shows reason, chooser, Binding Rule, rule version and Validation result with filters
- [ ] `offer-engine start` also starts the console
- [ ] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [ ] Committed: `T21: console clock controls and Decision log`
