# T24 — Customer Bots with bounded role-play
**Status:** DONE
**Prereqs:** T18, T23 · **Branch:** t24-customer-bots

## Goal
Each showcase Customer is played by its own Customer Bot: on receiving an Offer Card, an agent rates the message's
fit to the Persona Card, Ground Truth's chance is nudged by at most ±30%, a weighted coin flip decides, and the bot
replies in character with `/claim CODE` or `/notnow CODE`. M5 (PLAN §4.2; ADR 0004).

## Scope / files
- `src/offer_engine/commands/chats.py`: add `chats link-showcase`: links frozen Persona Card Customers to the
  `CUSTOMER_BOTS` usernames in order (kind `bot`), printing the mapping. Errors if there are fewer bots than cards.
- `src/offer_engine/customer_sim/app.py`: run **all** Customer Bots in one process (one python-telegram-bot
  `Application` per token in a shared asyncio loop). Replace T04's single-bot spike code.
- `src/offer_engine/customer_sim/roleplay.py`:
  - `rate_fit(client, model, persona_card, caption, terms) -> tuple[float, str]`: agent returns a fit score in
    [−1, 1] and a reply draft via a forced tool call.
  - `nudged_chance(p_base: float, fit: float) -> float` = `clip(p_base · (1 + 0.3 · clip(fit, −1, 1)), 0, 1)`:
    the nudge is **relative** and can never exceed ±30% whatever the agent returns.
  - `react(conn, offer, persona, client, rng) -> Reaction(buys, claim, reply_text)`: `p_base = p_buy(gt, depth)`;
    flip with the nudged chance; buyers Claim, non-buyers Claim with 25% else Not now; write `sim_offer_fates`
    (`source=bot_roleplay`, `buy_at` uniform in the window) and `sim_bot_responses(offer_id, p_base, fit, p_used,
    buys, reply)` (`schema/t24_sim_bot_responses.sql`).
  - The agent writes the in-character reply to match the outcome (it is told the outcome, not asked to decide).
- Reply message: the in-character text, then `/claim POE-…` or `/notnow POE-…` on its own line.

## Details
- The Customer Bot finds the Offer by the code in the caption and reads Ground Truth directly (the simulator side
  may; ADR 0002).
- Model from `FAST_AGENT_MODEL`. Agent outage → fit 0 (pure Ground Truth flip) and a neutral reply.
- Offers arrive from Triggers and the Daily Sweep (T19/T20) or `offer-engine trigger`; any source works.

Done as built:
- `rate_fit` returns `(fit, Replies(claim, not_now))`: one agent call writes both in-character replies, and the code sends the one the flip picked. So the agent still never decides, and a card costs one call, not two. The tool is `strict` with `tool_choice: auto`, because Opus 5.5, Sonnet 5.5 and Fable 5.1 reject forced tool choice (as in T11). Replies lose slash commands and `POE-` codes and are cut at 280 characters.
- `react(conn, offer, persona, client, model, rng)` also takes the model. It returns None for an Offer that isn't `sent`, already has a fate, or has no Ground Truth, so each Offer gets one reaction. `flip(p_used, rng)` holds the coin flips, and the 10,000-run test uses it directly. `p_base` is T18's `outcomes.buy_chance`, the same chance a Customer without a chat gets.
- The fate holds only `buys` and `buy_at`, uniform from the clock's time to expiry. The bot's own `/claim` or `/notnow` message changes the Offer's status. Like T18's fates, it cancels the Customer's organic orders in the window (Q39).
- `sim_bot_responses` has two more columns: `claims` and `created_at` (simulated).
- `react_to_card(db_path, code, chat_id, …)` is the bot's entry point. It acts only on Offers whose Customer is linked to that bot's chat, seeds the flip by (SEED, Offer ID), and waits up to 15 s for the Offer to leave `queued`. The Offer Bot marks an Offer `sent` only after Telegram accepts the card, so the card can arrive first; the live Check hit this.
- `chats link-showcase` skips optional cases (`persuadable`) when bots run short, and errors only when the required cards outnumber the bots (user's choice: `.env` has 7 bots for 8 cards).
- Two fixes outside the Scope, both needed for the Check. The Offer Bot sent cards to Customer Bots by numeric chat ID and Telegram answered "Chat not found", so `delivery.send_target` now uses the bot's `@username`. T10's Check had run only its Tester half. The Offer Bot's `/claim` and `/notnow` pattern now matches any line of a message, so the command can follow the reply. `delivery._offer` is now `offer_from_row`, which the role-play uses to draw the card's terms.
- Check run on 2026-10-23 on the 10k seed-7 world with 7 real Customer Bots in one process. `trigger cart-abandoned C09823` queued a Nudge. After `clock advance --hours 9`, @ap_customer5_bot got the card and replied "Thanks for the reminder, I'm still comparing basmati brands. I'll come back to it later." with `/notnow POE-VYAP91` (fit 0.7, chance 5.3% → 6.4%). The Offer Bot marked it `dismissed`. Over the next two simulated days, three more cards got in-character replies (two `/claim`, one `/notnow`), each accepted by the Offer Bot. No bot bought: their chances were 1–6%. A claiming buyer's Redemption is covered by `test_a_buyer_gets_a_roleplay_fate_and_redeems_through_t18`, not seen live. Three cards hit the `queued` race before the fix. The fix passes its tests but hasn't run on a fresh live card, because the frequency cap blocked every linked Customer after the Daily Sweeps.

## Tests
- `tests/test_roleplay.py`: property test (hypothesis) that `nudged_chance` stays within ±30% of `p_base` for any
  fit, including NaN and huge values; seeded flips over 10,000 runs match the nudged chance ±1 point; a fake agent
  gives the reply; outage path; fate and response rows written.
- Bots: manual, see Check.

## Check
`uv run offer-engine chats link-showcase && uv run offer-engine start`; `uv run offer-engine trigger cart-abandoned
<cart_abandoner id>` → in Telegram the Customer Bot receives the card and replies in character with `/claim` or
`/notnow`; `clock advance --days 3` → a claiming buyer's Offer shows `redeemed`.

## Done when
- [x] All Customer Bots run in one process, each linked to a showcase Customer
- [x] The nudge is bounded at ±30% by code, proven by a property test
- [x] Bots reply in character and act via `/claim` / `/notnow`; Redemption follows through T18
- [x] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [x] Committed: `T24: Customer Bots with bounded role-play`
