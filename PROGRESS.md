# Progress

What has been built, one line per feature, in the order it landed.

## Log

- [T01] Repo skeleton: uv project, `offer-engine` CLI that finds subcommands in `offer_engine/commands/`, `.env` settings (`uv run offer-engine --help`, `uv run offer-engine check-env`, `uv run pytest`)
- [T02] Shared types in `domain.py`, SQLite schema and migrations, Simulation Clock, versioned Rules store, Ground Truth boundary test (`uv run offer-engine db init`, `uv run offer-engine clock show`, `uv run offer-engine clock advance --days 1`)
- [T04] Offer Card PNG drawn from an Offer; Offer Bot sends a demo card on `/start` and acknowledges `/claim CODE`; first Customer Bot claims cards it receives; `offer-engine start` runs both bots (`uv run offer-engine start`, then `/start` to the Offer Bot; `uv run offer-engine demo-send` for the Customer Bot)

## Known issues / cuts

- `uv run ruff check .` reports 5 findings in `tickets/board.py` and `tickets/test_board.py` under ruff 0.17's default rules. `src/` and `tests/` are clean (`uv run ruff check src tests`).
- T04's bots have not run against Telegram yet: bot-to-bot delivery from `demo-send` and the Tester `/start` path are untested until someone runs the T04 Check with real tokens.
- The demo `/start` links the Tester's chat to Customer `C00001` itself, so the latest Tester to `/start` takes over that Customer. T25 adds per-Tester copies.
