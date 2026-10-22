# T16 — Estimated Lift v1: per-segment averages
**Status:** TODO
**Prereqs:** T09, T14 · **Branch:** t16-lift-v1

## Goal
The engine learns Estimated Lift per segment and Offer Type from the history's random past Offers, and every
Eligible Set option carries it, so the rules chooser and the agent rank options by it. M4 (PLAN §3.4, "Assumed ›
Deciding").

## Scope / files
- `src/offer_engine/lift/__init__.py`, `lift/segment_lift.py`:
  - `segment_of(state: CustomerState, now) -> tuple[str, str, bool]`: (loyalty tier, recency bucket ≤30 / 31–90 /
    >90 days since last order, coupon user = redeemed ≥2 past Offers).
  - `fit(conn) -> int`: for each segment × Offer Type, Lift = 7-day purchase rate after a past Offer − 7-day
    purchase rate at comparable no-offer moments (cart abandons and gaps without an Offer) for that segment. Fewer
    than 30 past Offers → Offer Type average. Writes `lift_estimates` (`schema/t16_lift_estimates.sql`) with the
    fit time.
  - `estimate(state, option) -> float | None`.
- `src/offer_engine/pipeline.py`: change **only** `default_lift_estimator()` to return `segment_lift.estimate`
  when `lift_estimates` has rows.
- `src/offer_engine/commands/lift.py`: `offer-engine lift fit`, `offer-engine lift show CUSTOMER_ID`.

## Details
- Learn only from observable tables (`offers`, `events`, `customers`); never `sim_*` (boundary test covers `lift`).
- Comparable no-offer moments are derived from observable events the same way T14 chose moments, not read from
  `sim_history_moments`.

## Tests
- `tests/test_segment_lift.py`: hand-built history with a known +10-point Lift for one segment recovers it
  within ±2 points; sparse segment falls back to the type average.
- On a 5,000-Customer seeded run, the correlation between segment Estimated Lift and mean Ground Truth Lift of the
  segment is positive (test lives in `tests/sim/`, which may read `sim_*`).

## Check
`uv run offer-engine lift fit && uv run offer-engine lift show C00042` → segment and a Lift per Offer Type;
`uv run offer-engine trigger cart-abandoned C00042` → Decision options now show Estimated Lift.

## Done when
- [ ] `lift fit` writes per-segment Estimated Lift from observable history
- [ ] Eligible Set options carry `estimated_lift` through `default_lift_estimator`
- [ ] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [ ] Committed: `T16: Estimated Lift v1 from random past Offers`
