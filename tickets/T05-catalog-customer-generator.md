# T05 — Catalog and Customer generator with organic history
**Status:** TODO
**Prereqs:** T02 · **Branch:** t05-generator

## Goal
`offer-engine generate --customers 200` fills the database with a catalog, Customers and 12 months of organic
events, deterministic for a seed. M2 (PLAN §2.1, §2.2).

## Scope / files
- `src/offer_engine/sim/__init__.py`, `src/offer_engine/sim/generate/__init__.py` with
  `STEPS: list[Callable[[GenContext], None]] = [catalog.step, customers.step, history.step]` and
  `run(conn, n_customers, months, seed)`. Later tickets append steps (T12 `ground_truth`, T14 `past_offers`).
- `sim/generate/catalog.py`: five categories with margins inside benchmark target 7 (e.g. grocery 15%,
  electronics 10%, fashion 45%, beauty 40%, home 30%); ~40 products each with Indian ₹ prices.
- `sim/generate/customers.py`: Customer IDs `C00001…`; signup date, city tier (1/2/3), device, acquisition
  channel, loyalty tier, points balance and expiry. Hidden behaviour traits (visit rate, buy propensity, basket
  size, category affinities, coupon affinity, churn hazard) go in table `sim_customer_traits`.
- `sim/generate/history.py`: `simulate_day(ctx, day: date, rng) -> list[Event]` for all Customers, and the step
  that loops it over the history window ending at the clock start (2026-12-01). Event kinds: `session`,
  `product_view`, `add_to_cart`, `cart_abandoned`, `order`, `delivered` (3 days after order), `return`,
  `points_earned`, `points_burned`, `points_expired`. Festive spike in the Diwali window (mid-Sep to early Nov
  2026, peak week early Nov).
- `src/offer_engine/schema/t05_sim_traits.sql`: `sim_customer_traits`.
- `src/offer_engine/commands/generate.py`: `offer-engine generate --customers N --months M --seed S`; wipes and
  refills generated tables; prints counts per table and event kind.

## Details
- Aim at calibration targets 1, 1a, 2, 5, 5a, 7, 8, 10, 11 in `docs/research/ecommerce-benchmarks.md`
  ("Suggested calibration targets"). T15 checks them; here, get close and note gaps.
- `simulate_day` is the per-day function the live world (T17) reuses: keep it free of history-only assumptions
  and don't make it read Offers (T14/T18 handle Offer effects).
- Same seed → identical database. Frozen Persona Cards (T23) depend on Customer IDs being stable.
- No Offers and no Ground Truth here.

## Tests
- `tests/sim/test_generate.py`: determinism (two runs with seed 7 give equal row hashes); every event's customer
  exists; `delivered` follows `order` by 3 days; festive weeks have more orders than the yearly weekly mean;
  margins within target 7.
- `tests/sim/test_simulate_day.py`: one day for a fixed context yields only listed kinds, timestamps inside the
  day.

## Check
`uv run offer-engine generate --customers 200 --seed 7` → counts table (5 categories, ~200 products, 200
Customers, thousands of events by kind); running it twice prints identical counts.

## Done when
- [ ] `generate` writes catalog, Customers, `sim_customer_traits` and 12 months of events
- [ ] `simulate_day` is a standalone per-day function
- [ ] Output is deterministic for a seed
- [ ] PROGRESS.md line added; `uv run pytest` green
- [ ] Committed: `T05: catalog and Customer generator`
