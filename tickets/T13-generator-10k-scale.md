# T13 — Generator at 10k scale
**Status:** TODO
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

## Tests
- `tests/sim/test_generate.py` still green (determinism, invariants).
- `tests/sim/test_generate_scale.py` marked `slow`: 10,000 Customers × 12 months completes under 5 minutes;
  `simulate_day` for 10,000 Customers under 5 s.
- Summary statistics (orders per active Customer, cart abandonment, top-20% spend share) on a 2,000-Customer run
  are within the target ranges in `docs/research/ecommerce-benchmarks.md`.

## Check
`time uv run offer-engine generate --customers 10000 --months 12` → finishes in < 5 min; counts printed.

## Done when
- [ ] 10k × 12 months generates in under 5 minutes
- [ ] `simulate_day` for 10k Customers runs in under 5 s
- [ ] Output still deterministic for a seed
- [ ] PROGRESS.md line added; `uv run pytest` and `uv run pytest -m slow` green
- [ ] Committed: `T13: generator at 10k scale`
