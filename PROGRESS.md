# Progress

What has been built, one line per feature, in the order it landed.

## Log

- [T01] Repo skeleton: uv project, `offer-engine` CLI that finds subcommands in `offer_engine/commands/`, `.env` settings (`uv run offer-engine --help`, `uv run offer-engine check-env`, `uv run pytest`)
- [T02] Shared types in `domain.py`, SQLite schema and migrations, Simulation Clock, versioned Rules store, Ground Truth boundary test (`uv run offer-engine db init`, `uv run offer-engine clock show`, `uv run offer-engine clock advance --days 1`)
- [T05] Generator: 5 categories, 200 products, Customers with hidden traits and 12 months of organic events from `simulate_day`, the same for a seed (`uv run offer-engine generate --customers 200 --seed 7`)
- [T06] Rules engine: Eligible Set for one Customer with a Binding Rule per limit; Opt-out, Holdout, Fatigue Pause, frequency cap, cooldown and eligibility short-circuit to No Offer (`uv run offer-engine eligible --demo`)
- [T07] Validation: `validate` recomputes the Eligible Set and reports every Rule a Proposal breaks, plus a hypothesis property test that 500 random rule-breaking Proposals never pass (`uv run pytest tests/test_validation.py tests/test_validation_property.py -q --hypothesis-show-statistics`)
- [T08] Caption Check: rejects captions with numbers or deadlines that differ from the Offer, invented urgency, unoffered promises, over 280 characters or blank; 65 bad and 20 good captions in `tests/data/captions.jsonl` (`uv run offer-engine caption-check "Hurry, 30% off tonight only!" --offer-type pct_category --param pct=15 --param cap=300 --category fashion`)

## Known issues / cuts

- `uv run ruff check .` reports 5 findings in `tickets/board.py` and `tickets/test_board.py` under ruff 0.17's default rules. `src/` and `tests/` are clean (`uv run ruff check src tests`).
- `offer-engine generate` deletes all Offers, Decisions and chat links and resets the Simulation Clock. Run it before linking Customer Bots or Testers, not after.
- The generator misses some calibration targets: grocery orders per buyer, top-1% spend share, weekly purchase chance and the share of points earners who never burn. The figures are in T05's ticket under Done as built; T15 tunes them.
- `offer-engine eligible` only takes `--demo` until T09 adds the Customer loader. Fatigue Pause counts from each dismissed Offer's creation time, since Offers don't record when they were dismissed.
- Validation needs a `send_at` on every Offer. The Fallback (T09) must set one, e.g. the start of the send window.
- The Caption Check misses a caption that names the wrong category ("15% off electronics" on a fashion Offer); the ticket has no reason code for it. It also lets "today" and "this week" through unless worded as a deadline ("today only", "this weekend"). Add rows to the tables in `caption_check.py` to tighten it.
