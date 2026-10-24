# T26 — Offline Policy simulator
**Status:** DONE
**Prereqs:** T11, T16, T18, T19, T20 · **Branch:** t26-policy-sim

## Goal
`offer-engine simulate` scores the four Policies (No Offers, Blanket 20%, Rules Only, Rules + Agent) on
Incremental Margin per ₹ of offer spend, with the supporting metrics, so the headline result exists. M6 (PLAN §5,
QnA Q15, Q31; ADR 0002; "Assumed › Outcomes").

## Scope / files
- `src/offer_engine/sim/policies.py`: `Policy(name, chooser_factory)`:
  - `no_offers`: always No Offer.
  - `blanket_20`: 20% off the Customer's top category, uncapped, at every Trigger, to everyone not in the Holdout
    or opted out. It bypasses the Eligible Set, so run it through `decide(..., chooser=...)` with Validation
    skipped by a `validate=False` keyword on `decide` (add it, default `True`, used only by this Policy).
  - `rules_only`: the rules chooser for everyone.
  - `rules_plus_agent`: the agent for everyone in the sample, model `FAST_AGENT_MODEL`.
- `src/offer_engine/sim/offline.py`: `run_policy(src_db, policy, days=28, seed, customer_ids=None) -> PolicyResult`:
  copy the database (`sqlite3` backup) to a temp file, force the Policy's chooser for every Customer, advance the
  world `days` days, then measure. Same seed and same starting state for every Policy (T17's keyed randomness).
- `src/offer_engine/sim/agent_cache.py`: cache agent responses in `sim_agent_cache(prompt_hash, response)`
  (`schema/t26_sim_policy.sql`, which also holds `sim_policy_results`), so reruns cost nothing.
- `src/offer_engine/sim/metrics.py`:
  - Incremental Margin = (margin − offer cost) under the Policy − margin under No Offers, over the same Customers,
    days and seed. Headline: Incremental Margin per ₹ of offer spend.
  - Supporting: Offers sent / Claimed / Redeemed; spend on Sure Things (Ground Truth class); Validation rejections
    and Fallbacks; lift by decile (Estimated Lift decile vs mean Ground Truth Lift).
- `src/offer_engine/commands/simulate.py`: `offer-engine simulate [--policies …] [--days 28] [--sample 500]`;
  prints a table and saves to `sim_policy_results` with the run time.

## Details
- No Offers, Blanket 20% and Rules Only run on all ~10k Customers. Rules + Agent runs on a stratified 500-Customer
  sample (stratify by the T16 segments), and every Policy is also reported on that sample so the comparison is
  like for like.
- Leave Tester copies out (`population_filter` from T25 if present; otherwise filter `is_tester_copy = 0`).
- Expect minutes, not hours: report runtime per Policy.
- Done as built: `pipeline.chooser_override(choose_for, validate=..., prefetch=...)` forces a Policy's chooser on
  every Decision in a run, Triggers and the Daily Sweep included, so `run_policy` needs no change to the world.
  `validate=False` still stops for opt-out and Holdout. Its `prefetch` hook lets Rules + Agent ask the agent for a
  whole Daily Sweep batch at once (16 threads); one call at a time, 4,500 calls would take about a day.
- Done as built: Rules + Agent runs on all Customers, with the agent for the sample and the rules chooser for the
  rest, so the weekly budget behaves as it would live. Only the sample is reported. `customer_ids` picks that sample.
- Done as built: Blanket 20% sends at every Trigger unless the Customer already holds a live Offer (queued, sent or
  claimed, not expired), so a Customer holds one at a time. It ignores every other Rule (QnA Q43).
- Done as built: the copies run with `PRAGMA synchronous = OFF`, which took a simulated day from 58 s to 24 s.
  Estimated Lift for the deciles is the segment estimate at the run's start. `--seed` and `--jobs` (Policies run
  in parallel processes, default 4) were added. Chats are deleted in each copy, so no Telegram sends happen.
- Done as built: the full run took 102 minutes, not minutes; see PROGRESS.md Known issues.

## Tests
- `tests/sim/test_metrics.py`: Incremental Margin on a hand-built pair of runs; spend on Sure Things; deciles.
- `tests/sim/test_offline.py` on a 300-Customer fixture with a fake agent: `no_offers` has zero spend and zero
  Incremental Margin; the source DB is unchanged after a run; rerun with the cache makes no agent calls; same seed
  gives identical results.

## Check
`uv run offer-engine simulate` → table like
`Policy | Offers | Spend | Incr. Margin | per ₹ spend` with Rules + Agent and Rules Only above Blanket 20% per ₹
(if not, record it honestly in PROGRESS.md Known issues).

## Done when
- [x] Four Policies run from the same starting state and seed without changing the live database
- [x] Incremental Margin per ₹ and the supporting metrics are computed and saved
- [x] Agent calls are cached
- [x] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [x] Committed: `T26: offline Policy simulator`
