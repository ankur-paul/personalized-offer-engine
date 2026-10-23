# T12 — Ground Truth: hidden response formula per Customer and Offer Type
**Status:** DONE
**Prereqs:** T05 · **Branch:** t12-ground-truth

## Goal
Every generated Customer gets a hidden response formula per Offer Type and a derived Response Class, readable only
by the simulator. M4 (PLAN §2.3; ADR 0002).

## Scope / files
- `src/offer_engine/sim/ground_truth.py`:
  - `GroundTruth(customer_id, offer_type, base, max_lift, k)`.
  - `p_buy(gt: GroundTruth, depth: float) -> float` = `clip(base + max_lift · (1 − e^(−depth/k)), 0, 1)`: chance
    of buying within 7 days.
  - `offer_depth(offer_type, params, catalog_category) -> float`: pct/100 for `pct_category`; amount ÷ category
    average basket for `flat_above_min`; 1 for `free_shipping` and `nudge`; (multiplier − 1) for
    `points_multiplier`.
  - `response_class(gts: list[GroundTruth]) -> str` (`persuadable`, `sure_thing`, `lost_cause`, `sleeping_dog`)
    using a typical Offer (15% off top category); thresholds as module constants.
  - `load(conn, customer_id) -> dict[OfferType, GroundTruth]`, `load_all(conn)`.
  - `step(ctx)`: generator step; append it to `STEPS` in `sim/generate/__init__.py` right after `history.step`.
- `src/offer_engine/schema/t12_sim_ground_truth.sql`: `sim_ground_truth(customer_id, offer_type, base, max_lift,
  k)`, `sim_response_class(customer_id, response_class)`.
- `src/offer_engine/commands/ground_truth.py`: `offer-engine ground-truth summary` prints Response Class shares and
  mean base / max Lift per Offer Type. Lives in `commands`, which may import `sim`.

## Details
- Parameters come from `sim_customer_traits` and observable history plus noise (PLAN §2.3): frequent recent buyers
  → high base; heavy coupon users → high discount sensitivity; small baskets and tier-2/3 cities → high
  free-shipping sensitivity; Nudge Lift small and positive except for Sleeping Dogs.
- `base` must match the organic weekly purchase chance the generator already produces for that Customer
  (calibration target 1a), so the world (T17) and Ground Truth agree.
- Response Class shares should land in calibration target 9 (Lost Causes 70–85%, Sure Things 5–15%, Persuadables
  3–10%, Sleeping Dogs 1–5%).
- Done as built: `base` has no noise. `organic_weekly_chance` computes it from the traits with the history funnel
  (`history.funnel`, shared with `session`) at normal demand, with no season. Customers who lapsed by the end of
  history get the lapsed visit rate. On the Check's world, active Customers have a mean base of 9.4% and a median
  of 3.5%, both above target 1a. That comes from the generator, which T15 tunes.
- Done as built: Response Class rules apply in order to 15% off. A negative Lift makes a Sleeping Dog, a base of
  at least 8% a Sure Thing, and a Lift of at least 5 points a Persuadable. Everyone else is a Lost Cause.
- Done as built: 3% of Customers are Sleeping Dogs, with max Lift −base × U(0.3, 0.8) for every Offer Type.
  Everyone else gets a positive max Lift with lognormal noise. Discounts use 0.13 × coupon_affinity², points 40%
  of that, free shipping 0.012 × basket_size^−1.5 × a city tier factor (0.6, 1.0, 1.5), and the Nudge 0.008.
- Done as built: `flat_above_min` is sitewide, so `offer_depth` needs the caller to pass the category whose basket
  it applies to and raises `ValueError` without one.
- Done as built: the Check on seed 7 gives Lost Cause 82.3%, Sure Thing 8.6%, Persuadable 5.9% and Sleeping Dog
  3.2%. A blanket 15% Offer lifts the mean buying chance by 47%, inside target 9's 30–120%. Customers who burned
  points on at least half their orders have a mean discount max Lift of 5.8%, against 0.9% for the rest.
- Done as built: the 2,000-Customer test world takes about 18 s, so `uv run pytest` went from 10 s to 28 s.

## Tests
- `tests/sim/test_ground_truth.py`: `p_buy` monotone in depth for positive `max_lift`, decreasing for negative;
  stays in [0,1]; `offer_depth` per type; class thresholds; on a 2,000-Customer seeded run the class shares fall in
  target 9; coupon-heavy Customers have higher mean discount `max_lift` than others.

## Check
`uv run offer-engine generate --customers 2000 && uv run offer-engine ground-truth summary` → class shares within
target 9 and a per-Offer-Type table.

## Done when
- [x] `sim_ground_truth` is filled for every Customer and Offer Type by the generator
- [x] Response Class is derived and stored
- [x] `ground-truth summary` prints shares within target 9
- [x] Boundary test still passes (no pipeline module reads it)
- [x] PROGRESS.md line added; `uv run pytest` green
- [x] Committed: `T12: hidden Ground Truth per Customer and Offer Type`
