# T15 — Calibration check script
**Status:** TODO
**Prereqs:** T13, T14 · **Branch:** t15-calibration

## Goal
`offer-engine calibrate` compares the generated population with the calibration targets and prints pass/fail per
metric, so data realism is checked automatically. M4 (PLAN §2.2; `docs/research/ecommerce-benchmarks.md`
"Suggested calibration targets").

## Scope / files
- `src/offer_engine/sim/calibration.py`: `Metric(id, name, value, lo, hi, passed)`; `measure(conn) -> list[Metric]`.
- `src/offer_engine/commands/calibrate.py`: `offer-engine calibrate [--strict]` prints a table; `--strict` exits
  1 on any failure.
- Tune generator constants (T05/T12/T14 modules) until the 10k default run passes, or document a miss.

## Details
Measure every numbered target 1–12 (and 1a, 3, 3a, 5a) in the benchmarks file that the data can express:
session-to-order conversion, weekly no-offer purchase chance (from Ground Truth `base`), cart abandonment,
cart-recovery from past Offers on abandoned carts, share of recovered carts that would have bought anyway (Ground
Truth), redemption per send, 90-day repeat among new Customers, orders per active Customer per year by category,
lapse, margins, spend concentration, Response Class shares, festive share of GMV, points breakage, opt-out per
message. Ranges come from that table; copy them into `calibration.py` with the target number beside each.
Category splits are judgement calls in the source: report them but don't fail `--strict` on them.
- Known miss from T14: Redemption per send is ~16% targeted and ~4.5% broadcast on 2,000 Customers (target 4:
  1.5–5%, 0.1–1%). Heavy grocery buyers (7-day base near 1) cause most abandoned carts, and every Customer who buys
  in an Offer's window redeems it. Tune T05's cart funnel or T12's base and Lift, not T14's mechanics.

## Tests
- `tests/sim/test_calibration.py`: each metric on a tiny hand-built DB gives the expected value; pass/fail logic at
  range edges.

## Check
`uv run offer-engine generate --customers 10000 && uv run offer-engine calibrate` → table where every non-category
metric passes; any miss listed under PROGRESS.md "Known issues / cuts".

## Done when
- [ ] `offer-engine calibrate` measures every target the data can express
- [ ] The default 10k seed passes `--strict`, or each miss is recorded in Known issues
- [ ] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [ ] Committed: `T15: calibration check against benchmarks`
