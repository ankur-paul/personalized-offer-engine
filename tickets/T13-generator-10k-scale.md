# T13 — Generator at 10k scale
**Status:** DONE
**Prereqs:** T05 · **Branch:** t13-generator-scale

## Goal
`offer-engine generate --customers 10000 --months 12` finishes in under 5 minutes on the laptop, and one simulated
day for 10k Customers (`simulate_day`) takes under 5 seconds, so the live world (T17) can run it. M4 (PLAN §2.2).

## Scope / files
- `src/offer_engine/sim/generate/history.py`: vectorise `simulate_day` with numpy over all Customers (arrays of
  traits in, event arrays out); keep its signature and behaviour.
- `src/offer_engine/sim/generate/customers.py`: vectorised trait and profile draws if they are a bottleneck.
- Bulk writes: one transaction per step, `executemany`, indexes created after the bulk insert.
- Don't edit `STEPS` in `sim/generate/__init__.py` (T12 and T14 append to it).

## Details
- Same seed must still give an identical database; distributions may shift slightly from T05's version but must
  stay within the calibration targets T05 aimed at.
- Profile the run first (`python -m cProfile`) and record the before/after timings in Details as `Done as built`.
- Done as built: T05's code already met every target, so nothing was vectorised (agreed with the user, 2026-10-23). A rewrite would change every draw and shift the data T12 and T14 build on. Timings on the laptop: `generate --customers 10000 --months 12` takes 83 s from the CLI and writes 3.24M events, and 78 s after T12 added the Ground Truth step. `simulate_day` for 10k Customers takes 0.16 s median and 0.7 s on the slowest day of the year. cProfile on 2,000 Customers puts 82% of the time in `simulate_day`, mostly per-session Python in `session()`, and 15% in `insert_events`. The 2,000-Customer run has 73.1% cart abandonment, 4.9 orders per buyer and a 71.4% top-20% spend share, all inside targets 2, 5a and 8. Bulk writes are unchanged: each step is already one transaction using `executemany`, and the `events_customer_at` index still builds during the insert. If T17 or later steps need speed, vectorise the session loop in `simulate_day` first.

## Tests
- `tests/sim/test_generate.py` still green (determinism, invariants).
- `tests/sim/test_generate_scale.py` marked `slow`: 10,000 Customers × 12 months completes under 5 minutes;
  `simulate_day` for 10,000 Customers under 5 s.
- Summary statistics (orders per active Customer, cart abandonment, top-20% spend share) on a 2,000-Customer run
  are within the target ranges in `docs/research/ecommerce-benchmarks.md`.

## Check
`time uv run offer-engine generate --customers 10000 --months 12` → finishes in < 5 min; counts printed.

## Done when
- [x] 10k × 12 months generates in under 5 minutes
- [x] `simulate_day` for 10k Customers runs in under 5 s
- [x] Output still deterministic for a seed
- [x] PROGRESS.md line added; `uv run pytest` and `uv run pytest -m slow` green
- [x] Committed: `T13: generator at 10k scale`
