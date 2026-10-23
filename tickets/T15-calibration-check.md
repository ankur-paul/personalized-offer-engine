# T15 — Calibration check script
**Status:** DONE
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
- Done as built: `Metric` has `unit` and `split` fields, and `passed` is a property. `measure(conn, end)` reads only
  events before `end` (the clock start), so it still works after `clock advance`. It leaves out targets the data
  can't express, such as seasonality on a history shorter than a year.
- Done as built: how each target is read on one 12-month history.
  - 1: orders per session. The category order (grocery and beauty above home and electronics) is a split metric
    showing the gap.
  - 1a: Ground Truth `base` of Customers not lapsed at the end. "Top decile" is the mean of the top 10%.
  - 3, 3a: past Offers at abandoned carts. For 3a, the mean `p_buy` at carts without an Offer is divided by the mean
    at carts with one. The draw is random, so this is the share of Redemptions that would have happened anyway.
  - 4: targeted means cart and long-gap moments (`sim_history_moments.trigger`).
  - 5: Customers who signed up in the history and whose first order is at least 90 days before its end.
  - 5a: Customers who ordered in the history. Per category: Customers who ordered in that category.
  - 6, lapse: Customers who signed up before the history and ordered in its first 90 days, lapsed by its end (the
    next ~9 months). Each one's main category sets the limit at 2× that category's median gap, capped at 180 days.
    The category's median gap is the median of its repeat buyers' own median gaps, because pooled gaps let
    grocery's heaviest buyers set a 10-day limit. New Customers are left out because most stay one-time, which the
    second figure measures.
  - 6, one-time: Customers who signed up in the history's first half and ordered.
  - 9: the blanket Lift and the Sure Things' share of redeemers are computed from Ground Truth at 15% off.
  - 10: festive window 15 Sep–7 Nov and peak week 1–7 Nov. The source gives the peak week as "~7%", so the range is
    our choice, 5–9%.
  - 11: only Customers who signed up in the history, since their earlier burns aren't visible. Breakage is expired ÷
    (burned + expired). "Members" are Customers who earned points on an order; the signup bonus alone doesn't count.
  - 12: `opted_out` events per past Offer sent.
- Done as built: tuning on the default 10k seed. Each change is followed by the target it fixed.
  - `VISIT_RATE_MEDIAN` 0.35 → 0.32 and every `CART_RATE` × 0.88 (1a, and conversion back under 2.5%).
  - `CHURN_HAZARD_MEDIAN` 0.0012 → 0.0004 (6, lapse).
  - Peak week demand 3.6 → 4.0 (10).
  - Opt-out 0.005 → 0.01 per message (12).
  - Points (11): Customers burn with chance `BURN_FLOOR` 0.4 + 0.6 × `coupon_affinity`, at least `WELCOME_BURN` 0.65
    in their first 60 days, and up to 30% of an order (was 20%). T12's coupon test still separates heavy burners
    (mean discount Lift 2.6× the rest's at 10k).
- Done as built: result on 10k, seed 7. Conversion 2.2%; weekly chance mean 7.5%, median 2.5%, top decile 40.5%;
  abandonment 73.0%; 90-day repeat 33.4%; 4.5 orders per active Customer a year; lapse 45.6%; one-time 57.2%; top
  20/10/1% 68.9/52.5/17.4% of spend; festive 19.3% of GMV, peak week 5.9%; breakage 35.6%; never burn 25.2%;
  opt-out 0.9%. Response Classes are unchanged and in target 9.
- Done as built: the misses, recorded in PROGRESS.md "Known issues".
  - Past Offers (agreed with the user, docs/QnA.md Q41): cart recovery 28.5% (3), 96.8% would have bought anyway
    (3a), Redemption per send 14.9% targeted and 4.2% broadcast (4).
  - Points breakage 35.6% (target 25–35%): 40% of new Customers never order, and their 100 welcome points always
    expire.
  - Category splits off target: grocery buyers order 6 times a year (target 24–40), fashion and beauty under 3, and
    first orders in home and electronics repeat at 25% and 22% (targets 10–20%, 5–15%).
- Done as built: `tests/sim/test_generate_scale.py` (slow) checks that the 10k world misses nothing beyond these.
- Done as built: two bugs from earlier tickets surfaced and are fixed here. T14's order removal took the first
  delivery of the same product and price, which could belong to an earlier order, so a removed order's delivery
  stayed. It now takes the delivery exactly 3 days after the order. T19's `trigger_log` references Customers but
  `generate` didn't wipe it, so `generate` failed after any Trigger had fired.

## Tests
- `tests/sim/test_calibration.py`: each metric on a tiny hand-built DB gives the expected value; pass/fail logic at
  range edges.

## Check
`uv run offer-engine generate --customers 10000 && uv run offer-engine calibrate` → table where every non-category
metric passes; any miss listed under PROGRESS.md "Known issues / cuts".

## Done when
- [x] `offer-engine calibrate` measures every target the data can express
- [x] The default 10k seed passes `--strict`, or each miss is recorded in Known issues
- [x] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [x] Committed: `T15: calibration check against benchmarks`
