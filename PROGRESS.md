# Progress

What has been built, one line per feature, in the order it landed.

## Log

- [T01] Repo skeleton: uv project, `offer-engine` CLI that finds subcommands in `offer_engine/commands/`, `.env` settings (`uv run offer-engine --help`, `uv run offer-engine check-env`, `uv run pytest`)
- [T02] Shared types in `domain.py`, SQLite schema and migrations, Simulation Clock, versioned Rules store, Ground Truth boundary test (`uv run offer-engine db init`, `uv run offer-engine clock show`, `uv run offer-engine clock advance --days 1`)
- [T05] Generator: 5 categories, 200 products, Customers with hidden traits and 12 months of organic events from `simulate_day`, the same for a seed (`uv run offer-engine generate --customers 200 --seed 7`)
- [T06] Rules engine: Eligible Set for one Customer with a Binding Rule per limit; Opt-out, Holdout, Fatigue Pause, frequency cap, cooldown and eligibility short-circuit to No Offer (`uv run offer-engine eligible --demo`)
- [T07] Validation: `validate` recomputes the Eligible Set and reports every Rule a Proposal breaks, plus a hypothesis property test that 500 random rule-breaking Proposals never pass (`uv run pytest tests/test_validation.py tests/test_validation_property.py -q --hypothesis-show-statistics`)
- [T08] Caption Check: rejects captions with numbers or deadlines that differ from the Offer, invented urgency, unoffered promises, over 280 characters or blank; 65 bad and 20 good captions in `tests/data/captions.jsonl` (`uv run offer-engine caption-check "Hurry, 30% off tonight only!" --offer-type pct_category --param pct=15 --param cap=300 --category fashion`)
- [T09] Decision pipeline: `decide` runs the Rules, the rules chooser, Validation and the Fallback, logs the Decision and queues the Offer. Also the Customer loader, the weekly budget, `trigger cart-abandoned`, `decisions` and `eligible --customer` (`uv run offer-engine generate --customers 200 && uv run offer-engine trigger cart-abandoned C00042 && uv run offer-engine decisions --last 5`)
- [T12] Ground Truth: `generate` stores a hidden response formula per Customer and Offer Type in `sim_ground_truth` and a Response Class in `sim_response_class`; shares land in calibration target 9 (`uv run offer-engine generate --customers 2000 && uv run offer-engine ground-truth summary`)
- [T11] Agent chooser: Claude picks one option or No Offer for chat-attached Customers and writes the caption and reason; Validation now runs the Caption Check, and an invalid pick or API failure falls back to the rules chooser with the agent's raw answer stored on the Decision (`uv run offer-engine generate --customers 200`, add a `chats` row for C00042, then `ANTHROPIC_API_KEY=bad uv run offer-engine trigger cart-abandoned C00042` shows `chooser=fallback`)
- [T13] Generator at 10k scale: 10k Customers × 12 months generate in about 80 s and `simulate_day` for 10k takes under 1 s, with slow tests for both and for the calibration of a 2,000-Customer run (`time uv run offer-engine generate --customers 10000 --months 12`, `uv run pytest -m slow tests/sim/test_generate_scale.py`)
- [T17] Live world day-step: `clock advance` runs organic events for every Customer hour by hour, delivers history's pending orders, marks Offers to Customers without a chat `sent` at `send_at`, and calls the outcomes, Triggers and Daily Sweep hooks (no-ops until T18–T20). One day for 10k Customers takes about 1.5 s (`uv run offer-engine generate --customers 10000 && uv run offer-engine clock advance --days 1`, `uv run pytest tests/sim/test_day_step.py`)

## Known issues / cuts

- `uv run ruff check .` reports 5 findings in `tickets/board.py` and `tickets/test_board.py` under ruff 0.17's default rules. `src/` and `tests/` are clean (`uv run ruff check src tests`).
- `offer-engine generate` deletes all Offers, Decisions and chat links and resets the Simulation Clock. Run it before linking Customer Bots or Testers, not after.
- The generator misses some calibration targets: grocery orders per buyer, top-1% spend share, weekly purchase chance and the share of points earners who never burn. The figures are in T05's ticket under Done as built; T15 tunes them.
- Fatigue Pause counts from each dismissed Offer's creation time, since Offers don't record when they were dismissed.
- Validation needs a `send_at` on every Offer. The Fallback (T09) must set one, e.g. the start of the send window.
- The Caption Check misses a caption that names the wrong category ("15% off electronics" on a fashion Offer); the ticket has no reason code for it. It also lets "today" and "this week" through unless worded as a deadline ("today only", "this weekend"). Add rows to the tables in `caption_check.py` to tighten it.
- The rules chooser values every category the Customer saw in the last 90 days and picks the most valuable one. A Customer who abandoned groceries can get a fashion Offer. Its Lift priors in `choosers/priors.py` are guesses until T16.
- The budget counts a Redemption's actual cost from the `order` event linked to the Offer by `offer_id`. Without that event it counts the worst-case cost, so T18 must link the order.
- `uv run pytest` takes about 28 s. The Ground Truth tests build a 2,000-Customer world for calibration target 9, about 18 s of that.
- T11's live test (`uv run pytest -m live tests/test_agent_live.py`) hasn't run: it needs `ANTHROPIC_API_KEY` and `OFFER_AGENT_MODEL` in `.env`. Until T10 adds `chats link`, link a Customer to a chat by inserting a `chats` row.
- The agent chooser doesn't use forced `tool_choice` (current models reject it with a 400). A reply without the tool call falls back to the rules chooser.
- `clock advance` on a 10k-Customer world gives about 2,600 sessions and 46 orders a day in early December, lower than T17's example. The history model leaves many Customers lapsed after a year; T15 calibrates it.
