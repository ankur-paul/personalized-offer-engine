# T17 — Live world day-step: organic events for every Customer on clock advance
**Status:** TODO
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
- [ ] `clock advance` runs organic events for every Customer hour by hour
- [ ] Offers to non-chat Customers are marked sent at `send_at`
- [ ] The three hook modules exist and are called in order
- [ ] One day for 10k Customers under 15 s
- [ ] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [ ] Committed: `T17: live world day-step on clock advance`
