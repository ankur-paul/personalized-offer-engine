# Progress

What has been built, one line per feature, in the order it landed.

## Log

- [T01] Repo skeleton: uv project, `offer-engine` CLI that finds subcommands in `offer_engine/commands/`, `.env` settings (`uv run offer-engine --help`, `uv run offer-engine check-env`, `uv run pytest`)
- [T03] `offer-engine setup` walks through creating the Offer Bot and 6–8 Customer Bots in BotFather, checks each token with `getMe`, and fills `.env` with mode 0600 (`uv run offer-engine setup`; re-run it to keep or replace values)

## Known issues / cuts

- `uv run ruff check .` reports 5 findings in `tickets/board.py` and `tickets/test_board.py` under ruff 0.17's default rules. `src/` and `tests/` are clean (`uv run ruff check src tests`).
- The BotFather menu path that `offer-engine setup` prints for Bot-to-Bot Communication Mode is not verified against BotFather. Fix `BOT_TO_BOT_PATH` in `src/offer_engine/setup_wizard.py` if it differs.
- When Telegram can't be reached, `offer-engine setup` treats every token as bad and keeps asking. Stop it with Ctrl-C; finished steps stay saved.
