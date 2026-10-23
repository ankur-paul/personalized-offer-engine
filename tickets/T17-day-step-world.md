# T17 — Live world day-step: organic events for every Customer on clock advance
**Status:** DONE
**Prereqs:** T09, T13 · **Branch:** t17-day-step

## Goal
`offer-engine clock advance --days 1` now runs the marketplace for all ~10k Customers hour by hour: organic
events, deliveries, points expiry, and Offers to Customers without a chat marked sent. It calls three hooks that
T18 (Offer outcomes), T19 (event Triggers) and T20 (Daily Sweep) fill in. M5 groundwork (PLAN §2.4, §2.5, "Assumed
› World and time").

## Scope / files
- `src/offer_engine/sim/world/__init__.py`, `sim/world/day_step.py`:
  - `DayReport(start, end, counts: Counter[str])`; hooks add their own counts.
  - `advance(conn, hours: int, rng_seed: int | None = None) -> DayReport`. For each simulated hour in order:
    1. At hour 0 of each day, generate the day's organic events with T13's `simulate_day` and spread them over
       hours; insert each hour's events as that hour is processed.
    2. Customers with an active (`sent` or `claimed`) Offer get **no organic order draw** that day; T18 decides
       their purchases.
    3. Points expiry at `points_expire_at`; `delivered` events 3 days after orders (if `simulate_day` doesn't
       already).
    4. Mark `queued` Offers to Customers **without** a `chats` row as `sent` once `send_at ≤ now`.
    5. Call hooks in this order: `sim.world.outcomes.on_hour(conn, now, report, rng)`,
       `offer_engine.triggers.on_hour(conn, now, new_events, report)`,
       `offer_engine.daily_sweep.on_hour(conn, now, report)`.
    6. Move the clock one hour.
  - Randomness keyed by (seed, Customer ID, day) so two runs from the same state with different Offers differ only
    where Offers changed behaviour (T26 relies on this).
- Create the three hook modules as no-ops with docstrings naming their ticket: `sim/world/outcomes.py` (T18),
  `src/offer_engine/triggers.py` (T19), `src/offer_engine/daily_sweep.py` (T20). Each later ticket fills only
  its own file.
- `src/offer_engine/commands/clock.py`: `advance` now calls `day_step.advance` and prints the DayReport counts.

## Details
- Performance: one simulated day for 10k Customers under 15 s including inserts.
- Hooks get `new_events` (this hour's inserted events) so Triggers don't re-scan the table.
- Done as built:
  - The day-step processes hour [t, t + 1h) as of its end. It inserts the hour's events, marks Offers sent where `send_at ≤ t + 1h`, moves the clock to t + 1h, then calls the hooks with `now = t + 1h`. The clock moves before the hooks, not after, so a hook that reads `clock.now` gets the same time as its `now`. The Daily Sweep hook sees `now = 10:00` once a day.
  - New table `sim_pending_events` (`schema/t17_sim_pending_events.sql`). At midnight `draw_day` draws the whole day's events into it, and each hour moves the due ones into `events`, so `clock advance --hours 5` then `--hours 19` gives the same events as `--days 1`. Deliveries and returns due on later days wait there too. A new last generate step, `sim.world.pending.save_scheduled`, saves the ones the history left past its end, so orders from the last 3 days of history get delivered.
  - Randomness is keyed by (seed, Customer ID, day): `draw_day` calls `simulate_day` once per Customer with a one-Customer `GenContext` and that Customer's stream. History generation is unchanged. A test checks that giving one Customer an Offer leaves every other Customer's events identical.
  - An active Offer means `sent` or `claimed` with `expires_at` after the day's start. Its holder still visits and carts, but `simulate_day` sets the order chance to 0 (new `GenContext.no_order_ids`), so every cart is abandoned that day.
  - The day-step updates `customers.points_balance` and `points_expire_at` hourly from the points events it inserts. Churn goes to `sim_customer_traits.churned_at` at each draw.
  - Tester copies have no `sim_customer_traits` row, so they get no organic events.
  - `rng_seed=None` means seed 7. `clock advance` takes `--seed`, prints the new time, then the counts (`nothing happened` when there are none).
  - `triggers.on_hour` and `daily_sweep.on_hour` type `report` as `Any`: pipeline modules may not import `offer_engine.sim`, where `DayReport` lives.
  - Timings: one day for 10k Customers takes 1.4 s from the CLI and 2.2 s under cProfile, 85% of it in `draw_day` (`products_by_category` re-sorts the catalog per Customer, 0.75 s). The slow test takes 24 s, mostly generating its world.
  - The Check prints lower counts than the example: `sessions 2,605 · product_views 5,243 · add_to_cart 196 · cart_abandoned 150 · orders 46 · delivered 59 · returns 1 · points_earned 59 · points_burned 11 · points_expired 20` on 2 Dec. That is the T05 history model in December after a year of churn, not the day-step. T15 calibrates it.

## Tests
- `tests/sim/test_day_step.py` on a 200-Customer fixture: advancing 24 h moves the clock 24 h and inserts events
  only inside that window; queued Offers to non-chat Customers become `sent`, chat ones stay `queued`; a Customer
  with an active Offer gets no organic order; hooks are called 24 times in the stated order (monkeypatched);
  same seed + same state → same events.
- `slow`: 10k Customers, one day, under 15 s.

## Check
`uv run offer-engine generate --customers 10000 && uv run offer-engine clock advance --days 1` → new date and
counts like `sessions 9,812 · orders 402 · cart_abandoned 1,130 · points_expired 87`.

## Done when
- [x] `clock advance` runs organic events for every Customer hour by hour
- [x] Offers to non-chat Customers are marked sent at `send_at`
- [x] The three hook modules exist and are called in order
- [x] One day for 10k Customers under 15 s
- [x] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [x] Committed: `T17: live world day-step on clock advance`
