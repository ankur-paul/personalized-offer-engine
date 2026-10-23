# T19 — Event Triggers on clock advance
**Status:** DONE
**Prereqs:** T17 · **Branch:** t19-event-triggers

## Goal
As the world runs, the four event Triggers fire Decisions through the pipeline: cart abandoned, points expiring
soon, long gap since last order, first order delivered. M5 (PLAN §3.1).

## Scope / files
- `src/offer_engine/triggers.py`: fill `on_hour(conn, now, new_events, report)` and add pure detectors:
  - `cart_abandoned`: each new `cart_abandoned` event.
  - `points_expiring`: a Customer whose `points_expire_at` is within `points_expiry_warning_days` and balance > 0;
    once per expiry date.
  - `long_gap`: days since the last order cross `long_gap_days` this hour; once per gap.
  - `first_order_delivered`: a `delivered` event for the Customer's first ever order.
  - For each hit call `pipeline.decide(conn, customer_id, kind, now)` and count Decisions per Trigger in the
    DayReport (`decisions.cart_abandoned`, …).
- `src/offer_engine/schema/t19_trigger_log.sql`: `trigger_log(customer_id, kind, key, at)` with a unique
  `(customer_id, kind, key)` for de-duplication.

## Details
- Rules still decide whether anything is sent; Triggers only ask.
- The pipeline side: no `sim` imports (boundary test).
- T09's `offer-engine trigger cart-abandoned` keeps working and should go through the same de-duplication.
- Done as built: keys are the cart's time, the expiry date, the last order's time, and `first` for the first delivery. The log row commits with the Decision, so a Decision that raises leaves the event free to fire again. `t19_trigger_log.sql` also adds an `events(kind, at)` index for the hourly long-gap lookup. The CLI refuses a second cart abandoned by the same Customer at the same simulated time. `tests/sim/test_day_step.py` stubs the Triggers hook so T17's exact checks on events and Offers still hold. At 10k Customers the first day gives `decisions.cart_abandoned 150 · decisions.long_gap 15`, below the Check's example, because the generated world is quieter (see PROGRESS Known issues).

## Tests
- `tests/test_triggers.py`: each detector on hand-built events; de-duplication (same expiry, same gap, same
  first order fires once); `on_hour` calls `decide` once per hit (monkeypatched).
- `tests/sim/test_triggers_world.py`: on a 200-Customer world, advancing 3 days logs Decisions for at least the
  cart-abandoned and long-gap Triggers.

## Check
`uv run offer-engine clock advance --days 1` → report includes `decisions.cart_abandoned 1,130 · decisions.long_gap 64 …`;
`uv run offer-engine decisions --last 10` shows Triggers other than `cart_abandoned`.

## Done when
- [x] The four Triggers fire on clock advance and run the pipeline
- [x] Each Trigger fires once per underlying event
- [x] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [x] Committed: `T19: event Triggers on clock advance`
