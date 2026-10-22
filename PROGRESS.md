# Progress

What has been built, one line per feature, in the order it landed.

## Log

- [T01] Repo skeleton: uv project, `offer-engine` CLI that finds subcommands in `offer_engine/commands/`, `.env` settings (`uv run offer-engine --help`, `uv run offer-engine check-env`, `uv run pytest`)
- [T02] Shared types in `domain.py`, SQLite schema and migrations, Simulation Clock, versioned Rules store, Ground Truth boundary test (`uv run offer-engine db init`, `uv run offer-engine clock show`, `uv run offer-engine clock advance --days 1`)
- [T06] Rules engine: Eligible Set for one Customer with a Binding Rule per limit; Opt-out, Holdout, Fatigue Pause, frequency cap, cooldown and eligibility short-circuit to No Offer (`uv run offer-engine eligible --demo`)

## Known issues / cuts

- `uv run ruff check .` reports 5 findings in `tickets/board.py` and `tickets/test_board.py` under ruff 0.17's default rules. `src/` and `tests/` are clean (`uv run ruff check src tests`).
- `offer-engine eligible` only takes `--demo` until T09 adds the Customer loader. Fatigue Pause counts from each dismissed Offer's creation time, since Offers don't record when they were dismissed.
