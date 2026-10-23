# T03 — Interactive bot setup script
**Status:** BLOCKED (needs human: run `offer-engine setup` with real BotFather tokens and confirm the Bot-to-Bot menu path)
**Prereqs:** T01 · **Branch:** t03-setup-script

## Goal
A new developer runs `uv run offer-engine setup` and is walked through creating the Offer Bot and 6–8 Customer
Bots in BotFather, enabling Bot-to-Bot Communication Mode on each, and filling `.env`. M1 (PLAN §7, QnA Q36).

## Scope / files
- `src/offer_engine/commands/setup.py`: `offer-engine setup`.
- `src/offer_engine/setup_wizard.py`:
  - `run_wizard(io: WizardIO, env_path: Path) -> None` (WizardIO wraps input/print so tests can script it).
  - `merge_env(env_path, updates: dict[str, str]) -> None`: keeps existing keys, comments and order; adds or
    replaces only the given keys; file mode 0600.
  - `check_token(token) -> str | None`: calls Telegram `getMe` through python-telegram-bot `Bot.get_me()`;
    returns the bot's username or `None`.

## Details
Steps, each printed as a numbered screen, waiting for Enter or input:
1. Open @BotFather, `/newbot`, name the Offer Bot. Paste the token → `check_token` → store `OFFER_BOT_TOKEN`,
   `OFFER_BOT_USERNAME`. A bad token re-asks.
2. In BotFather, enable Bot-to-Bot Communication Mode for the Offer Bot (print the exact menu path from current
   BotFather; verify it when building this ticket and note it in Details as `Done as built`).
3. Ask how many Customer Bots (6–8, default 7). For each: create, paste token, check, remind to enable
   Bot-to-Bot mode. Store as `CUSTOMER_BOTS=user:token,…`.
4. Anthropic API key (input hidden with `getpass`), `OFFER_AGENT_MODEL`, `FAST_AGENT_MODEL` (point to the
   `claude-api` skill / docs for current IDs; don't hard-code).
5. Write `.env`, then run `check-env` and print its result.
- Never print a token or key back. Re-running the wizard offers to keep each existing value.

Done as built:
- `.env` is saved after each step (and after each Customer Bot), not only in step 5, so a stopped run keeps what
  was entered. On a re-run, Customer Bots that are kept but number fewer than 6 are topped up. Step 5 runs the
  check-env report (`check_env.report`, split out of `check_env.run`).
- With no `.env`, the wizard starts from `.env.example`, so the comments carry over.
- Bot tokens are read hidden too, like the API key. A token must look like `digits:30+ chars` before `getMe` is
  called. A token already used by another bot in this setup is refused.
- `check_token` returns `None` both for a rejected token and for an unreachable Telegram, so offline the wizard
  keeps asking. Ctrl-C exits with code 130 and keeps the finished steps.
- The BotFather switch is in the Mini App, not in `/mybots → Bot Settings`. Telegram's docs give no menu path.
  Checked by hand on 2026-10-23: @BotFather → Open (Mini App) → the bot → Bot-to-Bot Communication Mode. The wizard
  prints this path (`BOT_TO_BOT_PATH` in `setup_wizard.py`).
- The wizard does not ask for `DB_PATH`, `SEED` or `CONSOLE_PASSWORD`. They have defaults or are optional, so
  check-env lists them `missing` unless they were set by hand.

## Tests
- `tests/test_setup_wizard.py`: `merge_env` preserves unrelated lines and comments; scripted IO run with
  `check_token` mocked writes all keys; a bad token is re-asked; output never contains a token.

## Check
`uv run offer-engine setup` with real BotFather tokens → `.env` filled, final `check-env` shows all keys `set`.

## Done when
- [x] `offer-engine setup` walks all five steps and writes `.env` with mode 0600
- [x] Tokens are verified with `getMe` before saving
- [x] PROGRESS.md line added; FEATURES.md mentions setup; `uv run pytest` green
- [x] Committed: `T03: interactive bot setup script`
- [ ] Check run with real BotFather tokens and the Bot-to-Bot menu path confirmed
