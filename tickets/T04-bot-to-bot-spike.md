# T04 — Bot-to-bot spike: Offer Card to a Customer Bot and a Tester
**Status:** DONE
**Prereqs:** T02 · **Branch:** t04-bot-spike

## Goal
Prove the riskiest plumbing on day 1: the Offer Bot sends a code-rendered Offer Card to one Customer Bot and to a
Tester; the Customer Bot replies `/claim CODE` and the Offer Bot acknowledges. One start command runs both bots.
M1 (PLAN §4.1, §8; ADR 0005).

## Scope / files
- `src/offer_engine/offer_card.py`:
  - `offer_terms(offer: Offer, catalog_names: dict[str, str]) -> list[str]`: the term lines, e.g.
    `"15% off Fashion"`, `"Up to ₹300 off"`, `"₹200 off orders above ₹1,499"`, `"Free shipping"`,
    `"2x points on Beauty"`, `"Code POE-7K3Q9X"`, `"Valid until 4 Dec, 10:00"`. A Nudge has no money line.
  - `render_offer_card(offer, catalog_names) -> bytes`: a PNG (Pillow, ~800×450) drawing exactly `offer_terms`.
  - Bundle an OFL font that has the ₹ glyph (e.g. Noto Sans) in `src/offer_engine/assets/fonts/` with its licence.
- `src/offer_engine/offer_bot/app.py`: `build_app(settings) -> Application`, `main()`. Polling.
  `HANDLER_MODULES` list, starting with `demo`, written one entry per line so later tickets (T10, T25, T34)
  add or replace their own line without conflicting.
- `src/offer_engine/offer_bot/handlers/demo.py`: `/start` from a human links the chat as a Tester of demo
  Customer `C00001` (insert a minimal Customer row if missing) and sends the demo card; `/claim CODE` replies
  `Claimed POE-…. Show this code at checkout.` and logs it.
- `src/offer_engine/customer_sim/app.py`: runs the **first** Customer Bot from `CUSTOMER_BOTS`; on a photo from the
  Offer Bot, reads the code from the caption and replies `/claim CODE` to the Offer Bot by username.
- `src/offer_engine/commands/demo_send.py`: `offer-engine demo-send` sends the demo card to the first Customer
  Bot by `@username`.
- `src/offer_engine/commands/start.py`: `offer-engine start` launches `PROCESSES` as subprocesses (Offer Bot,
  Customer Bot simulator), prefixes their output, stops all on Ctrl-C. T21 adds the console entry.

## Details
- The demo Offer is a hard-coded `Offer` (15% off fashion, ₹300 cap, code `POE-DEMO01`, valid 3 days from clock
  now). The caption is fixed text plus a final line `Code: POE-DEMO01`, which the Customer Bot parses.
- Bot API 10.0: bots message each other by username only when both have Bot-to-Bot Communication Mode on.
  Check current python-telegram-bot support for it; if the library lags, call the HTTP method directly and note
  it in Details as `Done as built`.
- **Contingency:** if bot-to-bot delivery or the reply doesn't work as documented, commit the working Tester path,
  set `**Status:** BLOCKED (bot-to-bot: <what failed>)` and tell the user. PLAN §8 contingency then applies
  (Customer Bots become a console view).

Done as built:
- No direct HTTP call was needed. python-telegram-bot 22.8 targets Bot API 10.0, whose changelog says bots can
  "send messages to other bots via username if both bots enabled bot-to-bot communication". `send_photo` and
  `send_message` take `@username` as `chat_id`.
- Telegram's docs don't say whether a bot's `/claim CODE` in a private chat carries a `bot_command` entity, so the
  Offer Bot matches `/claim` with a text regex (`CLAIM_PATTERN` in `handlers/demo.py`), not a `CommandHandler`.
  A wrong or missing code gets a hint, and only `POE-DEMO01` is claimed.
- The Customer Bot claims each code once and ignores everything except photos and text from the Offer Bot.
  Telegram asks bot-to-bot handlers to "terminate predictably", and this rules out reply loops.
- The font is Noto Sans (variable, OFL) as `assets/fonts/NotoSans-VF.ttf`. Pillow selects the Regular and Bold
  instances. `format_inr` groups digits the Indian way (`₹1,50,000`).
- `/start` from a bot is ignored. The demo Customer row is `C00001`, a silver-tier Android Customer who signed up
  30 days before clock now. `chats` holds one chat per Customer, so the latest Tester to `/start` takes over
  `C00001`. T25 adds per-Tester copies.
- `offer-engine start`: when a process exits 0 the rest keep running, and when one fails all stop. With no
  `CUSTOMER_BOTS` the simulator exits 0, so the Offer Bot still serves Testers. Both bot processes set httpx
  logging to WARNING, because httpx logs request URLs, and Telegram URLs contain the token.
- Check run by hand on 2026-10-23 with real tokens: the Tester `/start` got the card and `/claim POE-DEMO01` was
  acknowledged; after `demo-send`, @ap_customer1_bot replied `/claim POE-DEMO01`, the Offer Bot logged
  `Claim POE-DEMO01 from bot @ap_customer1_bot` and its acknowledgement reached the Customer Bot. A second card
  with the same code got no reply.

## Tests
- `tests/test_offer_card.py`: `offer_terms` for every Offer Type; the PNG decodes and has the expected size; a
  Nudge card has no ₹ line.
- `tests/test_customer_sim_parse.py`: code parsing from captions (present, absent, lowercase).
- Bots themselves: manual, see Check.

## Check
`uv run offer-engine start`; in Telegram send `/start` to the Offer Bot → card arrives; tap nothing, send
`/claim POE-DEMO01` → "Claimed POE-DEMO01…". In another terminal `uv run offer-engine demo-send` → the Customer
Bot's chat with the Offer Bot shows the card and the bot's `/claim POE-DEMO01` reply, and the Offer Bot logs the
Claim.

## Done when
- [x] Offer Card PNG renders terms for all five Offer Types from an `Offer`
- [x] A Tester `/start` receives the demo card
- [x] The Customer Bot receives the card from the Offer Bot and its `/claim` is acknowledged (or ticket BLOCKED per Contingency)
- [x] `offer-engine start` runs both bots
- [x] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [x] Committed: `T04: bot-to-bot spike with Offer Card`
- [x] Check run with real bot tokens (covers the two unticked items above)
