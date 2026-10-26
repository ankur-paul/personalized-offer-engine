# T35 — Decision trace
**Status:** TODO
**Prereqs:** — · **Branch:** t35-decision-trace

## Goal
Every live Decision records why it came out as it did, stage by stage, and `offer-engine decisions explain <id>`
prints that trace. The pipeline also hands each stage to an optional listener as it finishes, so the live engine
page (T39) can animate a Decision as it happens. Part 1 of the demo pass: T35 / T36 → T37 → T38 / T39 → T40
(PLAN "Assumed (approved 2026-10-26)", QnA Q44–Q51).

## Scope / files
- `src/offer_engine/schema/t35_decision_traces.sql`: `decision_traces(decision_id INTEGER PRIMARY KEY REFERENCES
  decisions(id), trace TEXT NOT NULL)`, with the trace as JSON.
- `src/offer_engine/trace.py` (new; a pipeline module, so it never reads `sim_*`):
  - `Stage(name: str, title: str, summary: str, data: dict)`. `name` is one of `trigger`, `customer`, `checks`,
    `eligible_set`, `valuation`, `agent`, `validation`, `fallback`, `offer`. `summary` is one plain-English line,
    e.g. "Margin floor caps grocery at 10%".
  - `Trace(stages: list[Stage])`, with `to_json()` and `from_json()`.
  - A listener type, `StageListener = Callable[[Stage], None]`.
- `src/offer_engine/pipeline.py`: `decide(..., on_stage: StageListener | None = None)` and the same keyword on
  `decide_many`. `_decide` builds the stages in order and calls `on_stage` after each one. `_write` inserts the
  trace in the same transaction as the Decision. Change only `_decide`, `_eligible`, `_attempt` and `_write`: T36
  edits `_client` and `new_code` in parallel.
  - **checks**: each check `rules._short_circuit` makes (opt-out, Holdout, Fatigue Pause, frequency cap, cooldown,
    eligibility, budget), each marked passed or stopping. A stop ends the trace at `offer` with No Offer.
  - **eligible_set**: each option's ranges, its Binding Rule per parameter, its worst-case cost and Estimated
    Lift, plus the send window.
  - **valuation**: the rules chooser's best parameters and value per option
    (Lift × margin − redemption chance × cost), computed with `rules_chooser.assess`, even when the agent decides.
  - **agent**: the model, the full user prompt, the raw tool input, and the time the call took. Skipped (with the
    reason) when the rules chooser decides.
  - **validation**: every check from the new `ValidationResult.checks`, each marked passed or failed, and the
    Caption Check result.
  - **fallback**: present only when the agent's proposal was rejected or the call failed.
  - **offer**: Offer Type, parameters, caption, send time, expiry, cost, or No Offer with its reason.
- `src/offer_engine/validation.py` and `domain.py`: add `ValidationResult.checks: tuple[str, ...] = ()`, the
  names of the checks `validate` ran. This is additive; `failures` doesn't change. **Write it test-first**
  (CLAUDE.md › Testing).
- `src/offer_engine/commands/decisions.py`: `decisions explain <id>` prints the trace one stage per block.
  `decisions` with no subcommand keeps today's `--last` and `--customer` behaviour.
- `src/offer_engine/sim/offline.py` and `sim/preview.py`: pass `trace=False` (a new keyword on `decide_many`) so
  the offline Policy simulator and Preview impact store no traces.
- `console/pages/2_decisions.py`: under the selected row, an expander "Why" lists the stage summaries.

## Details
- A trace never holds Ground Truth or anything from a `sim_*` table. The boundary test covers `trace.py` too: add
  it to `PIPELINE_MODULES` in `tests/test_ground_truth_boundary.py`.
- Measure the Daily Sweep on 10k Customers (`uv run pytest -m slow tests/test_daily_sweep.py`) before and after.
  If tracing makes it more than 15% slower, store full traces only for chat-attached Customers and keep the
  `checks` and `offer` stages for the rest. Record the numbers as `Done as built`.
- Decisions made before this ticket have no trace. `decisions explain` says so instead of failing.

## Tests
- `tests/test_trace.py`:
  - A cart-abandoned Decision with a fake agent has all nine stages in order, and the listener is called once per
    stage in the same order.
  - A Holdout Customer's trace stops at `checks`, naming `holdout_pct`.
  - A rejected agent proposal produces a `fallback` stage that names the failures.
  - The trace JSON round-trips.
- `tests/test_validation.py`: `checks` names every check, for passing and failing proposals alike. The property
  test in `tests/test_validation_property.py` still passes.
- `tests/test_cli.py` (or a new `tests/test_decisions_explain.py`): `decisions explain` on a fixture Decision
  prints each stage title.

## Check
```
uv run offer-engine generate --customers 300 && uv run offer-engine lift fit
uv run offer-engine trigger cart-abandoned C00042
uv run offer-engine decisions explain 1
```
The last command prints Trigger, Customer, Checks (each passed), Eligible Set (options with Binding Rules and
Estimated Lift), Valuation (value per option), Agent (or "skipped: no chat"), Validation (each check passed),
and Offer.

## Done when
- [ ] Each live Decision stores a trace; `decisions explain <id>` prints it
- [ ] `decide` calls `on_stage` once per stage, in order
- [ ] `ValidationResult.checks` lists the checks `validate` ran; the property test passes
- [ ] `simulate` and Preview impact store no traces; Daily Sweep timing recorded under Details
- [ ] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [ ] Committed: `T35: decision trace`
