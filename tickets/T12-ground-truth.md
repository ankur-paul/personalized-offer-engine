# T12 — Ground Truth: hidden response formula per Customer and Offer Type
**Status:** TODO
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

## Tests
- `tests/sim/test_ground_truth.py`: `p_buy` monotone in depth for positive `max_lift`, decreasing for negative;
  stays in [0,1]; `offer_depth` per type; class thresholds; on a 2,000-Customer seeded run the class shares fall in
  target 9; coupon-heavy Customers have higher mean discount `max_lift` than others.

## Check
`uv run offer-engine generate --customers 2000 && uv run offer-engine ground-truth summary` → class shares within
target 9 and a per-Offer-Type table.

## Done when
- [ ] `sim_ground_truth` is filled for every Customer and Offer Type by the generator
- [ ] Response Class is derived and stored
- [ ] `ground-truth summary` prints shares within target 9
- [ ] Boundary test still passes (no pipeline module reads it)
- [ ] PROGRESS.md line added; `uv run pytest` green
- [ ] Committed: `T12: hidden Ground Truth per Customer and Offer Type`
