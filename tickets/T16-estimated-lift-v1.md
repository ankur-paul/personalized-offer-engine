# T16 — Estimated Lift v1: per-segment averages
**Status:** DONE
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
- T14 sends at most one past Offer per Customer per 7 days and lets it decide purchases for those 7 days
  (docs/QnA.md Q39), so "bought in 7 days" after a past Offer equals its `p_buy`. A no-offer moment inside an
  Offer's 7 days isn't comparable: skip it, as T14 does.
- Done as built: `estimate` is `SegmentLift.estimate(state, option)`, from `segment_lift.load(conn, now)`. The
  recency bucket needs the Decision's time, which `CustomerState` doesn't carry, so `default_lift_estimator` takes
  `(conn, now)` and `decide` passes them. That call site is the only other line changed in `pipeline.py`.
- Done as built: `estimated_lift` stores max Lift, the observed Lift divided by the past Offers' mean saturation
  on the prior's curve (`priors.lift_at`). The rules chooser and the agent prompt already read it as Lift at full
  depth; a raw rate difference at random depths would undercount it by 15–35%. `observed_lift` keeps the raw
  difference, and the ±2-point test checks both.
- Done as built: no-offer moments include the Friday 18:00 broadcast slots as well as abandoned carts and 45-day
  gaps. Without them the no-offer side would hold mostly cart abandoners, who buy far more often, and every Lift
  would come out negative. The history's start is the earliest event's date.
- Done as built: Holdout Customers are left out, as T14 left them out. Including them put heavy buyers who never
  had a past Offer into the non-coupon segments and drove one segment's estimate to −26%.
- Done as built: `offer-engine generate` now deletes `lift_estimates` with the rest of the old world (one line in
  `sim/generate/__init__.py`), so a fit never outlives its history.

## Tests
- `tests/test_segment_lift.py`: hand-built history with a known +10-point Lift for one segment recovers it
  within ±2 points; sparse segment falls back to the type average.
- On a 5,000-Customer seeded run, the correlation between segment Estimated Lift and mean Ground Truth Lift of the
  segment is positive (test lives in `tests/sim/`, which may read `sim_*`).
- Done as built: the 5,000-Customer tests take about 50 s and are marked `slow` (`uv run pytest -m slow
  tests/sim/test_segment_lift_truth.py`). Correlation is 0.29. A second test checks each Offer Type average
  against T14's mean `p_buy` with and without an Offer, within 1 point.

## Check
`uv run offer-engine lift fit && uv run offer-engine lift show C00042` → segment and a Lift per Offer Type;
`uv run offer-engine trigger cart-abandoned C00042` → Decision options now show Estimated Lift.

## Done when
- [x] `lift fit` writes per-segment Estimated Lift from observable history
- [x] Eligible Set options carry `estimated_lift` through `default_lift_estimator`
- [x] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [x] Committed: `T16: Estimated Lift v1 from random past Offers`
