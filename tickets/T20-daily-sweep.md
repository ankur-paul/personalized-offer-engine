# T20 — Daily Sweep
**Status:** DONE
**Prereqs:** T17 · **Branch:** t20-daily-sweep

## Goal
Once per simulated day at 10:00 the Daily Sweep considers every Customer for an Offer (win-back and lapse),
chat-attached Customers first. M5 (PLAN §3.1, "Assumed › Deciding").

## Scope / files
- `src/offer_engine/daily_sweep.py`: fill `on_hour(conn, now, report)`: when `now.hour == 10`, run
  `sweep(conn, now) -> Counter`:
  - Order: chat-attached Customers first, then the rest in an order shuffled by a seed derived from the date.
  - Skip Customers who already had a Decision in the last 24 simulated hours.
  - Bulk-load states with `customers.load_customer_states` in batches; call `pipeline.decide(..., TriggerKind.daily_sweep, now)`.
  - Count Decisions by outcome (`sweep.offer`, `sweep.no_offer`, by binding rule) into the DayReport.
- If `decide` per Customer is too slow, add a batch path in `pipeline.py` as a **new** function
  `decide_many(conn, customer_ids, trigger, now)` added at the end of the file (don't change `default_chooser` / `default_lift_estimator`, which T11 and T16 edit).

## Details
- Performance: the sweep over 10k Customers with the rules chooser under 60 s.
- Decisions with No Offer are logged too (the console can hide them).

Done as built:
- `pipeline.decide_many` was needed (per-Customer `decide` re-queries the budget each call, about 6 ms each). It shares a new `_decide` with `decide` and returns a generator, adding each written Offer's cost to the in-memory budget the way `budget_state` counts it. A test checks it gives the same Decisions as `decide` one at a time while the budget runs out.
- The 24-hour skip is "a Decision after now − 24 h", so yesterday's 10:00 sweep doesn't block today's. Counts also include `sweep.skipped`; Binding Rules count as `sweep.binding.<rule>`. `clock advance` prints the sweep outcomes after `offers_sent`.
- The first sweep on 10k Customers gave `sweep.offer 8,357 · sweep.no_offer 1,506`, not 820 / 8,950: 7,970 of the Offers are ₹0 Nudges from the rules chooser (Known issues).
- `tests/sim/test_day_step.py` stubs the sweep hook; `tests/sim/test_triggers_world.py` counts sweep Decisions apart from Trigger Decisions.

## Tests
- `tests/test_daily_sweep.py`: runs only at 10:00; chat-attached Customers decided first (budget fixture that runs
  out after 3 Offers gives them to chat Customers); the 24-hour skip; counts in the report.
- `slow`: 10k sweep under 60 s.

## Check
`uv run offer-engine clock advance --days 1` → report includes `sweep.offer 820 · sweep.no_offer 8,950 · …`.

## Done when
- [x] The sweep runs once per simulated day at 10:00 over every Customer
- [x] Chat-attached Customers are decided first
- [x] 10k sweep under 60 s
- [x] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [x] Committed: `T20: Daily Sweep`
