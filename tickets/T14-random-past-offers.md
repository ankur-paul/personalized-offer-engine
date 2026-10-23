# T14 — History with partly random past Offers and their outcomes
**Status:** DONE
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
- Done as built:
  - An Offer decides whether the Customer buys in the 7 days after the send, not just in the validity window, and
    `p_buy` uses the base at the moment (season, lapse) via `ground_truth.with_base` (docs/QnA.md Q39, Q40, agreed
    with the user). A Redeemer keeps the organic orders after the Redemption; a non-buyer loses all 7 days' orders.
    Removing all 7 days for everyone took orders per buyer from 4.9 to 3.8, below target 5a; now 4.7.
  - One past Offer at a time per Customer: moments inside an earlier Offer's 7 days aren't drawn. Overlapping Offers
    each drew a purchase, so cart moments showed +5 points of Lift against a true +0.5.
  - Removed organic orders take their burn, delivery, points earned and return with them, including any still due in
    `ctx.scheduled`. Points are then replayed in time order for every Customer whose orders changed, and loyalty
    tiers are recomputed (`history.update_customers`). Redemption orders get a delivery, points (times the multiplier
    for a points Offer), a points burn drawn on `coupon_affinity` and maybe a return, like organic orders.
  - The redemption `order` carries the basket before discount (as `budget.redemption_cost` reads it) and the
    Offer's id; a new `offer_redeemed` event carries the cost. Opt-outs write an `opted_out` event and set
    `customers.opted_out`. Opt-out is 0.5% per message (no doubling: at most one Offer a week), dismissal 5% of
    non-claimers.
  - Moments: abandoned carts at their time, long gaps counted from signup and each order, broadcasts Fridays 18:00;
    sends move into the send hours. Only moments whose 7 days end inside the history count. A % off cap and a flat
    amount's minimum basket follow the live Rules' shapes; codes come from the seeded stream.
  - `sim_history_moments` holds every drawn moment, with `offer_id` (NULL = don't send) and the chance of buying,
    so the per-type test can compare Redemption with `p_buy`.
  - Tests run on a shared 2,000-Customer world (`tests/sim/conftest.py`, also used by T12's tests) rather than
    5,000; each Offer Type still has 4,000+ sends.
  - Target 4 misses: on 2,000 Customers the targeted Redemption rate is ~16% and broadcast ~4.5% (targets 1.5–5%,
    0.1–1%). Heavy grocery buyers, with a 7-day base near 1, cause most abandoned carts. Agreed with the user to
    record the miss and leave the tuning to T15; `history summary` prints it.
  - 2,000 Customers generate in about 18 s (T14 adds about 4 s); 10k in about 100 s.

## Tests
- `tests/sim/test_past_offers.py`: no past Offer to a Holdout Customer; Redemption rate per Offer Type on a seeded
  5,000-Customer run is within ±2 points of the mean `p_buy` of recipients; Claim ≥ Redemption; redemption orders
  carry the discount; targeted redemption rate falls in calibration target 4 (1.5–5%) overall. (As built: 2,000
  Customers; target 4 is reported, not asserted. See Details.)

## Check
`uv run offer-engine generate --customers 2000 && uv run offer-engine history summary` → table of past Offers per
type with send counts and Claim/Redemption rates.

## Done when
- [x] Past Offers with `source=history_random` exist with Ground Truth outcomes
- [x] No Holdout Customer got a past Offer
- [x] `history summary` prints rates per Offer Type
- [x] PROGRESS.md line added; `uv run pytest` green
- [x] Committed: `T14: history with random past Offers`
