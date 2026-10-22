# T01 — Repo skeleton: uv project, CLI, config, docs
**Status:** DONE
**Prereqs:** — · **Branch:** t01-skeleton

## Goal
A fresh clone runs `uv sync`, `uv run offer-engine --help` and `uv run pytest`. Every later ticket builds on this
layout. First ticket of M1 (PLAN §8); layout in PLAN "Assumed › Code layout".

## Scope / files
- `pyproject.toml`: uv project, `requires-python = ">=3.12"`, src layout, script
  `offer-engine = "offer_engine.cli:main"`. Add **every** runtime dependency the plan needs now, so later tickets
  don't edit this file: `python-telegram-bot[job-queue]`, `anthropic`, `streamlit`, `pillow`, `numpy`, `pandas`,
  `python-dotenv`, `scikit-learn`. Dev group: `pytest`, `hypothesis`, `ruff`. Configure pytest
  (`testpaths = ["tests"]`, markers `live` and `slow`, both skipped unless `-m live` / `-m slow`).
- `src/offer_engine/__init__.py`, `src/offer_engine/commands/__init__.py`.
- `src/offer_engine/config.py`: `Settings` frozen dataclass and `load_settings(env_file: Path | None = None) -> Settings`
  reading `.env` via python-dotenv. Fields: `offer_bot_token`, `offer_bot_username`,
  `customer_bots: list[tuple[str, str]]` (parsed from `CUSTOMER_BOTS=username1:token1,username2:token2`),
  `anthropic_api_key`, `offer_agent_model`, `fast_agent_model`, `db_path` (default `data/offer_engine.db`),
  `seed` (default 7), `console_password` (optional).
- `src/offer_engine/cli.py`: `main(argv=None)`. argparse with subparsers; discovers every module in
  `offer_engine.commands` with `pkgutil.iter_modules` and calls its `register(subparsers)`. No command list is
  kept anywhere.
- `src/offer_engine/commands/check_env.py`: `offer-engine check-env` prints each key as `set` or `missing`, never
  the value. Exits 1 if `OFFER_BOT_TOKEN`, `OFFER_BOT_USERNAME` or `ANTHROPIC_API_KEY` is missing.
- `.env.example`: every key above with a one-line comment; no real values.
- `PROGRESS.md`: title, one-line purpose, `## Log`, `## Known issues / cuts` (CLAUDE.md › Docs).
- `FEATURES.md`: title, `## What it does` (empty list), `## Known limits`.
- `data/.gitkeep` (`data/generated/` and `*.db` are already gitignored).

## Details
- Python 3.14 is installed locally; 3.12 is the floor so hosts with older Python work (T29).
- Command modules must import heavy dependencies inside their handler, not at module top, so `--help` stays fast.

- Done as built: `check-env` also takes `--env-file PATH`, reports a malformed `CUSTOMER_BOTS` or `SEED` as an
  error and exits 1. `python -m offer_engine` runs the CLI. `FEATURES.md` starts with the `check-env` bullet
  instead of an empty list. The process environment overrides `.env`; empty values count as missing.

## Tests
- `tests/test_cli.py`: `--help` lists `check-env`; a temporary command module in a monkeypatched package is
  discovered without editing `cli.py`.
- `tests/test_config.py`: `CUSTOMER_BOTS` parsing (empty, one, several, malformed → clear `ValueError`); defaults.
- `tests/test_check_env.py`: missing required key → exit 1; output never contains a token value.

## Check
`uv sync && uv run offer-engine --help && uv run offer-engine check-env; uv run pytest -q` → help lists
`check-env`, check-env lists keys as missing (no `.env` yet) and exits 1, tests pass.

## Done when
- [x] `uv run offer-engine --help` lists `check-env`
- [x] Commands are discovered from `offer_engine/commands/` with no list to edit
- [x] `.env.example`, `PROGRESS.md`, `FEATURES.md` exist; `PROGRESS.md` has its first `[T01]` line
- [x] `uv run pytest` green
- [x] Committed: `T01: repo skeleton, CLI and config`
