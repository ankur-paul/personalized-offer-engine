# T14 — History with partly random past Offers and their outcomes
**Status:** TODO
**Prereqs:** T06, T12 · **Branch:** t14-past-offers

## Goal
The generated history contains past Offers sent partly at random, as A/B tests would be, with Claims and
Redemptions settled by Ground Truth, so Estimated Lift (T16) can be learned. M4 (PLAN §2.2, §3.4, "Assumed ›
Outcomes").

## Scope / files
- `src/offer_engine/sim/generate/past_offers.py`: `step(ctx)`, appended to `STEPS` after `ground_truth.step`.
  - Moments: each `cart_abandoned` event, each 45-day gap since last order, and a weekly broadcast slot.
  - At each moment send with probability 0.3 (never to Holdout Customers, via `rules.in_holdout`), Offer Type
    uniformly at random including Nudge, depth uniformly within plausible ranges (pct 5–30, flat ₹100–500, points
    1.5–3x).
  - Outcome: buy within the validity window with `p_buy(gt, depth)`; if buying, add an `order` event (basket from
    traits, discount applied, margin after offer cost) and mark the Offer `redeemed`; every Redeemer is Claimed;
    25% of non-Redeemers Claim; otherwise `expired`. Small chance of `dismissed` and of `opted_out` per message
    (calibration target 12).
  - Write `offers` rows with `source=history_random`, and `offer_claimed` / `offer_dismissed` events.
- Remove organic orders that the Offer outcome replaces in that window so a Customer doesn't double-buy (the
  Offer outcome decides the purchase for that window, as T18 does live).
- `src/offer_engine/commands/history.py`: `offer-engine history summary` prints past Offers by type with send,
  Claim and Redemption rates, and the same for no-offer comparison moments.

## Details
- Vectorise; must run at 10k Customers within the 5-minute budget T13 sets for the whole `generate`.
- Store the no-offer comparison moments (moments that drew "don't send") in `sim_history_moments`
  (`schema/t14_sim_history_moments.sql`) for T16's tests only; T16 itself must learn from observable data
  (offers + events), not this table.

## Tests
- `tests/sim/test_past_offers.py`: no past Offer to a Holdout Customer; Redemption rate per Offer Type on a seeded
  5,000-Customer run is within ±2 points of the mean `p_buy` of recipients; Claim ≥ Redemption; redemption orders
  carry the discount; targeted redemption rate falls in calibration target 4 (1.5–5%) overall.

## Check
`uv run offer-engine generate --customers 2000 && uv run offer-engine history summary` → table of past Offers per
type with send counts and Claim/Redemption rates.

## Done when
- [ ] Past Offers with `source=history_random` exist with Ground Truth outcomes
- [ ] No Holdout Customer got a past Offer
- [ ] `history summary` prints rates per Offer Type
- [ ] PROGRESS.md line added; `uv run pytest` green
- [ ] Committed: `T14: history with random past Offers`
