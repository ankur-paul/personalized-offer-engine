# T10 — Offer delivery and Customer responses
**Status:** BLOCKED (needs human: Tester half of the Check, tapping the buttons in Telegram)
**Prereqs:** T04, T09 · **Branch:** t10-delivery

## Goal
A queued Offer to a chat-attached Customer arrives in Telegram as an Offer Card with Claim / Not now / Stop; each
response updates the database, including Opt-out and the dismissals that feed the Fatigue Pause. Customer Bots
use the same actions by text. M2/M3 (PLAN §4.1, §4.3, §3.3; ADR 0005; "Assumed › World and time").

## Scope / files
- `src/offer_engine/schema/t10_outbox.sql`: `outbox(id, chat_id, text, created_at, sent_at)`.
- `src/offer_engine/offer_bot/delivery.py`: a JobQueue job every 5 wall-clock seconds:
  - queued Offers whose Customer has a `chats` row and `send_at ≤ clock.now()` → `send_photo` (Offer Card from
    T04's renderer) with caption = agent/template caption + blank line + `Code: POE-…`, and inline buttons
    **Claim** / **Not now** / **Stop**; set `status=sent`, record `sent_at`.
  - unsent `outbox` rows → `send_message`, set `sent_at`.
- `src/offer_engine/offer_bot/responses.py`: `claim(conn, code, chat_id)`, `dismiss(conn, code, chat_id)`,
  `stop(conn, chat_id)`, `restart(conn, chat_id)`: pure-ish DB functions returning the reply text.
- `src/offer_engine/offer_bot/handlers/responses.py`: callback buttons and text commands `/claim CODE`,
  `/notnow CODE`, `/stop`; register it in `HANDLER_MODULES` after `demo`.
- `src/offer_engine/commands/chats.py`: `offer-engine chats link CUSTOMER_ID --bot @username` (kind `bot`) and
  `chats list`.

## Details
- Claim → `status=claimed`, event `offer_claimed`; reply `Claimed! Your code is POE-…. It's valid until 4 Dec, 10:00.`
- Not now → `status=dismissed`, event `offer_dismissed`; reply `No problem. We'll ease off for a bit.`
- Stop → `customers.opted_out=1`, event `opted_out`, outstanding `queued` Offers for that Customer →
  `withdrawn`; reply `You won't get any more offers. Send /start any time to turn them back on.`
- `/start` from a chat whose Customer is opted out → `opted_out=0`, event `opted_in`. (T25 later extends `/start`
  for new Testers; keep the opt-in logic in `responses.restart` so T25 can call it.)
- Claim on an expired, withdrawn or other-Customer code → `That code isn't active any more.` / `That code isn't yours.`
- Only the chat linked to the Offer's Customer may act on it.
- Remove T04's `demo-send` path only if it now duplicates this; the demo `/start` card can stay for Testers until T25.

Done as built:
- `t10_outbox.sql` also adds `offers.sent_at` (simulated time). The Offer Bot sets it to the clock's time when it
  sends, and T17's `mark_sent` sets it to `send_at` for Customers without a chat.
- Delivery skips Offers already past `expires_at` and Customers who opted out. A send Telegram refuses stays
  queued and is retried on the next run. `delivery.queue_message` adds an `outbox` row for T18.
- `demo-send` and the hard-coded `POE-DEMO01` card are removed: the code isn't in the database, so it couldn't be
  claimed. The demo `/start` now links the Tester to C00001, opts the chat back in through `responses.restart`
  and replies with text. From a Customer Bot, `/start` (command or text) only opts back in.
- Replies the ticket left open: Not now on a claimed Offer gives "You've already claimed POE-…." and keeps the
  Claim; a dismissed Offer can't be claimed; claiming or dismissing twice repeats the reply with no second
  event; an unknown or still-queued code is "isn't active any more"; Stop/`/start` from an unlinked chat gives
  "This chat isn't linked to a Customer."; `/start` when already opted in gives "You're already getting offers."
- A tapped card loses its buttons; the code still works by text.
- `chats link` takes the Customer Bot's chat ID from the number before the colon in its token (no Telegram
  call) and moves the chat off any other Customer, so a chat serves one Customer. `chats list` shows bot
  usernames and opt-outs.
- apscheduler logging is set to WARNING in the bot processes; it logged every 5-second run at INFO.
- Check, Customer Bot half, run on 2026-10-23 with real tokens on a 200-Customer world: `chats link C00042
  --bot @ap_customer1_bot`, `start`, `trigger cart-abandoned C00042` → `chooser=agent` Offer POE-ZJNASF; the card
  reached @ap_customer1_bot, it sent `/claim POE-ZJNASF`, the Offer Bot replied "Claimed! … valid until 4 Dec,
  10:00." and the database shows `claimed`, `sent_at` and an `offer_claimed` event. This is also the first
  live run of T11's agent path.

## Tests
- `tests/test_responses.py`: claim/dismiss/stop/restart state changes and reply texts; wrong chat; expired code;
  stop withdraws queued Offers.
- `tests/test_delivery_select.py`: the selection query picks only chat-attached, due, queued Offers.

## Check
`uv run offer-engine chats link C00042 --bot @<customer bot>`; `uv run offer-engine start`; `uv run offer-engine
trigger cart-abandoned C00042` → card arrives in the Customer Bot's chat within ~5 s. As a Tester (T04 `/start`
links you to C00001): `offer-engine trigger cart-abandoned C00001` → card; tap **Not now** → reply and
`offer-engine decisions` / DB shows `dismissed`; tap **Stop** → opted out; `/start` → opted in.

## Done when
- [x] Queued Offers to chat-attached Customers are delivered as Offer Cards with three buttons
- [ ] Claim, Not now, Stop and `/start` (opt-in) update the database by button and by text
- [x] Outbox messages are delivered
- [x] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [ ] Committed: `T10: Offer delivery and Customer responses`
