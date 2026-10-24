# T27 — Console: results dashboard
**Status:** DONE
**Prereqs:** T21, T26 · **Branch:** t27-results-dashboard

## Goal
A Results page in the console shows the Policy comparison headline and the supporting views, readable by a
marketer without explanation. M6 (PLAN §5, §6).

## Scope / files
- `console/pages/4_results.py` with sections:
  1. **Policies**: Incremental Margin per ₹ of offer spend by Policy (bar), plus a table of Offers, spend,
     Incremental Margin, from the latest `sim_policy_results`; shows the run time and the command to rerun.
  2. **Live funnel vs Holdout**: live Offers sent → Claimed → Redeemed, and order rate per Customer of
     treated vs Holdout Customers since the clock start.
  3. **Wasted on Sure Things**: offer spend that went to Sure Things, live and per Policy.
  4. **Validation**: rejections and Fallbacks per day, top failure codes.
  5. **Lift by decile**: Estimated Lift decile vs mean Ground Truth Lift.
- `src/offer_engine/sim/live_metrics.py`: live funnel, treated-vs-Holdout order rates, live Sure-Thing spend
  (pure functions over the DB; may read `sim_*`).

## Details
- Use the `dataviz` skill before writing chart code.
- Tester copies excluded from every population number.
- Each chart has a one-line plain-English caption saying what to look for.
- Done as built: `live_metrics.py` also holds Validation by day and the failure-code counts. "Treated" is every
  population Customer outside the Holdout, offered or not, at today's `holdout_pct`. The latest run is read by
  `console/data.py` (`latest_policy_run`). A radio switches the Policy sections between the sample (default) and
  all Customers. Validation shows a success line instead of an empty chart when nothing failed, and failure codes
  carry a plain-English meaning. The rerun command shows `--days` and `--seed` only. Checked on a copy of the
  10k seed-7 world after `simulate --policies blanket_20,rules_only --days 3 --sample 300` and 3 simulated days.

## Tests
- `tests/sim/test_live_metrics.py`: funnel counts and Holdout comparison on a hand-built DB.
- `tests/console/test_results_page.py` (AppTest): page renders with and without `sim_policy_results` rows.

## Check
Run `offer-engine simulate`, advance the live clock a few days, open Console › Results → all five sections show
data.

## Done when
- [x] Results page shows the Policy headline and the four supporting views
- [x] Live funnel compares treated Customers with the Holdout
- [x] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [x] Committed: `T27: console results dashboard`
