# T25 — Testers: pick a Customer, get their Offers
**Status:** DONE
**Prereqs:** T18, T23 · **Branch:** t25-testers

## Goal
A human starts the Offer Bot, picks a Customer from Persona Card buttons or "Surprise me", gets their own copy of
that Customer, asks for Offers with `/offers`, and sees Claims turn into simulated orders. M5 (PLAN §4.1, §4.4,
QnA Q10, Q16, Q38; "Assumed › Outcomes").

## Scope / files
- `src/offer_engine/testers.py`: `create_tester_copy(conn, source_customer_id, telegram_user_id) -> str`: copies
  the Customer row (`is_tester_copy=1`, `source_customer_id`), its last 180 days of events and points, as
  `<id>-t<telegram user id>`; reuses an existing copy. Links the chat (kind `tester`). Copies the hidden simulator
  rows the world needs (`sim_customer_traits`, `sim_ground_truth`) through a function in `offer_engine/sim/` (this
  module must not touch `sim_*` itself; call `sim.testers.copy_hidden(conn, source, copy)` from the handler).
- `src/offer_engine/offer_bot/handlers/testers.py`, registered in `HANDLER_MODULES` by replacing the `demo` line
  in place (T34 may append `haggle` at the end of the list in parallel):
  - `/start`: `Welcome! Pick a Customer to play. You'll get the offers our engine decides for them.` + one button
    per frozen Persona Card (name + case) + **Surprise me**. Also calls `responses.restart` for opted-out chats.
  - Pick → create copy; reply with the Persona Card text and `Simulated date: 2 Dec 2026. Offers arrive as the
    marketing team advances the clock. Send /offers to ask for one now.`
  - Holdout pick → `You're playing {name}, who is in the control group (Holdout). They never receive offers, so we
    can measure what offers change.`
  - `/offers` → `pipeline.decide(..., TriggerKind.on_request, now)`; if No Offer, explain with the Binding Rule in
    plain words (e.g. `No offer right now: Asha already got 2 offers this week.`).
  - `/whoami`, `/switch` (pick again).
- Exclude `is_tester_copy` Customers from population metrics (note for T26/T27; add a `population_filter` SQL
  snippet in `customers.py`).

## Details
- Each Tester gets their own copy so two judges playing the same Customer don't use up each other's caps.
- Tester copies are chat-attached, so the agent decides for them (T11) and the Daily Sweep considers them first.
- Redemption messages come from T18 via the outbox.
- Done as built: there is no `sim.testers.copy_hidden`. T17 and T18 had already decided that copies have no `sim_*`
  rows: they draw no organic events, and their outcomes use the source's Ground Truth through `source_customer_id`.
  The copy also carries the source's finished Offers from the last 180 days, with new codes (QnA Q42). Switching opts
  the old copy out and withdraws its queued Offers, so the Daily Sweep stops sending to a copy nobody plays; picking
  it again opts it back in. The pick reply shows the clock's date instead of a fixed 2 Dec 2026, and `/offers` says
  when an Offer goes out if the send window hasn't opened. `population_filter(alias)` is a function; the filters
  already written by hand in `segment_lift`, `calibration` and persona selection stay as they are.

## Tests
- `tests/test_testers.py`: copy created once per (Customer, Telegram user); copy shares the source's Holdout;
  events copied; handler replies for pick, Surprise me, Holdout, `/offers` with and without an Offer (fake
  update/context objects).

## Check
From a personal Telegram account: `/start` → buttons; pick the cart abandoner → Persona Card; `/offers` → Offer
Card with an agent caption; tap **Claim**; in the console advance 3 days → `Simulated order: …` message or the
Offer expires. Pick the Holdout Customer → control-group message, `/offers` → none.

## Done when
- [x] `/start` offers Persona Card buttons and Surprise me; picking creates a per-Tester copy
- [x] Holdout pick explains the control group
- [x] `/offers` runs the pipeline on request and explains No Offer
- [x] Tester copies are excluded from population metrics
- [x] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [x] Committed: `T25: Testers pick a Customer and receive Offers`
