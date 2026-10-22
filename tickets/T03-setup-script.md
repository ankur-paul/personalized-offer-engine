# T03 — Interactive bot setup script
**Status:** TODO
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

## Tests
- `tests/test_setup_wizard.py`: `merge_env` preserves unrelated lines and comments; scripted IO run with
  `check_token` mocked writes all keys; a bad token is re-asked; output never contains a token.

## Check
`uv run offer-engine setup` with real BotFather tokens → `.env` filled, final `check-env` shows all keys `set`.

## Done when
- [ ] `offer-engine setup` walks all five steps and writes `.env` with mode 0600
- [ ] Tokens are verified with `getMe` before saving
- [ ] PROGRESS.md line added; FEATURES.md mentions setup; `uv run pytest` green
- [ ] Committed: `T03: interactive bot setup script`
