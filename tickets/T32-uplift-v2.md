# T32 — Stretch: Estimated Lift v2, two-model uplift learner
**Status:** PARKED (after the demo pass, T35–T40; QnA Q47)
**Prereqs:** T16 · **Branch:** t32-uplift-v2

## Goal
*Stretch:* a two-model uplift learner (with-Offer and without-Offer classifiers per Offer Type) replaces the
per-segment averages when it grades better against Ground Truth. M7 (PLAN §3.4).

## Scope / files
- `src/offer_engine/lift/two_model.py`: features from observable data only (profile, recency, frequency, monetary,
  category mix, coupon history); scikit-learn gradient-boosted or logistic classifiers for 7-day purchase with and
  without each Offer Type; `fit(conn)`, `estimate(state, option)`. Model saved to `data/models/` (gitignored).
- `src/offer_engine/commands/lift.py`: `lift fit --model two-model|segment`; `LIFT_MODEL` setting in `.env`.
- `src/offer_engine/pipeline.py`: `default_lift_estimator()` picks by `LIFT_MODEL`.

## Details
- No `sim_*` reads (boundary test covers `lift`).
- Grade both models with T26's lift-by-decile metric; keep `segment` as the default unless `two-model` is better,
  and record the comparison in Details as `Done as built`.

## Tests
- `tests/test_two_model.py`: recovers a known heterogeneous Lift on synthetic data better than segment averages.

## Check
`uv run offer-engine lift fit --model two-model && uv run offer-engine simulate --policies rules_only` → lift-by-
decile table for v2 alongside v1.

## Done when
- [ ] Two-model learner trains and estimates from observable data
- [ ] Lift-by-decile comparison against v1 recorded
- [ ] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [ ] Committed: `T32: two-model uplift learner`
