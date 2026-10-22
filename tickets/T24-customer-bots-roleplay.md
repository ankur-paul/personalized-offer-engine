# T24 — Customer Bots with bounded role-play
**Status:** TODO
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
- [ ] All Customer Bots run in one process, each linked to a showcase Customer
- [ ] The nudge is bounded at ±30% by code, proven by a property test
- [ ] Bots reply in character and act via `/claim` / `/notnow`; Redemption follows through T18
- [ ] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [ ] Committed: `T24: Customer Bots with bounded role-play`
