# T18 — Offer outcomes: Claims, Redemptions and expiry by Ground Truth
**Status:** TODO
**Prereqs:** T10, T12, T17 · **Branch:** t18-offer-outcomes

## Goal
In the live world, sent Offers resolve: Customers without a chat Claim and Redeem by Ground Truth, Testers'
Claims turn into simulated Redemptions with a message, Customer Bots' outcomes come from their role-play (T24), and
unredeemed Offers expire. M5 (PLAN §2.5, §4.1, §4.3; ADR 0002, 0004; "Assumed › Outcomes").

## Scope / files
- `src/offer_engine/schema/t18_sim_offer_fates.sql`: `sim_offer_fates(offer_id, buys, buy_at, claim_at, p_used,
  source)` where `source` is `ground_truth` | `tester_claim` | `bot_roleplay`.
- `src/offer_engine/sim/world/outcomes.py`: fill `on_hour(conn, now, report, rng)`:
  1. Newly `sent` Offers without a fate:
     - Customer without a chat: draw `buys` with `p_buy(gt, depth)`; `buy_at` uniform within validity; `claim_at`
       at or before `buy_at` for buyers, and for 25% of non-buyers a random time; small chance of `dismissed` or
       Opt-out per calibration target 12.
     - Customer Bot: leave alone; T24 writes the fate when the bot reacts.
  2. Newly `claimed` Offers of a **Tester** without a fate: draw `buys` with
     `p / (p + 0.25·(1 − p))` (chance of buying given a Claim, p = `p_buy`), `buy_at` uniform in the rest of the
     window.
  3. Due `claim_at` → `status=claimed`, `offer_claimed` event.
  4. Due `buy_at` with `buys` → `order` event (basket drawn around the category average, discount applied, margin
     after offer cost) and `status=redeemed`, `offer_redeemed` event. For a Tester, add an outbox row:
     `Simulated order: ₹1,240 basket, code POE-… used. You saved ₹186.`
  5. `expires_at ≤ now` and not redeemed → `status=expired`. `withdrawn` Offers are skipped.
  - Add counts to the DayReport (`claimed`, `redeemed`, `expired`, `opted_out`).
- `src/offer_engine/sim/world/offer_economics.py`: `redemption_order(offer, catalog, rng) -> (basket, discount,
  margin)` shared with T14's past Offers if convenient (don't change T14's results).

## Details
- Sleeping Dogs: `p_buy` < base, so sending them an Offer lowers their purchases: that's intended.
- A Customer with an active Offer who doesn't "buy" gets no organic order that day (T17 already skips them).
- Per docs/QnA.md Q39, the Offer's outcome should decide whether the Customer buys in the 7 days after the send:
  no organic orders before the Redemption, or for all 7 days if they don't buy. Then live Lift matches Ground
  Truth's 7-day `p_buy` and T14's history. T14's `past_offers` shows the shape.

## Tests
- `tests/sim/test_outcomes.py`: over 20,000 fixture Offers the redemption rate matches mean `p_buy` within ±1
  point; Claim ≥ Redemption; Tester Claim → fate drawn with the conditional formula, outbox text on Redemption;
  bot Offers untouched until a fate exists; expiry; withdrawn skipped; redemption order margin = basket margin −
  offer cost.

## Check
Generate 2,000 Customers, `offer-engine trigger cart-abandoned` on a few, `clock advance --days 4` → report shows
`claimed`, `redeemed`, `expired`; as a Tester (C00001 via T04 `/start`), claim an Offer and advance days → the
"Simulated order…" message arrives (or the Offer expires).

## Done when
- [ ] Non-chat Offers resolve by Ground Truth into Claims, Redemptions or expiry
- [ ] Tester Claims resolve with the conditional formula and a Redemption message
- [ ] Customer Bot Offers wait for a role-play fate
- [ ] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [ ] Committed: `T18: Offer outcomes by Ground Truth`
