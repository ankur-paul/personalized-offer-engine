# T38 — Demo scenarios: safety net and marketer controls
**Status:** TODO
**Prereqs:** T37 · **Branch:** t38-demo-safety-controls

## Goal
Four more scenarios. Two show that the engine stays safe when the agent misbehaves, and two show what a marketer
controls. With them, `demo check` covers all ten scenarios from QnA Q48. Part 3a of the demo pass: T37 → T38 /
T39 → T40.

## Scope / files
- `src/offer_engine/demo/tamper.py`: `tampered(chooser, *, params=None, caption=None)` wraps a chooser so its
  Proposal gets the given parameters or caption. It applies only inside a scenario, through `pipeline.Override`;
  nothing outside `demo/` imports it.
- `src/offer_engine/demo/scenarios.py`: append these after T37's six, in this order:
  - `agent-breaks-rule`, "Validation rejects a rule-breaking proposal; the Fallback decides". The setup tampers
    the agent's answer to 40% off, above the loyalty-tier maximum. Expect `chooser=fallback`, a failure naming
    the broken limit, and a valid Fallback Offer.
  - `manipulative-caption`, "The Caption Check blocks invented urgency". The caption becomes
    `"Hurry, 30% off tonight only!"`. Expect a Caption Check failure and the Fallback.
  - `rule-change`, "A Rule change flips a Decision". Run the Decision under the current Rules, save a tighter Rule
    as author `demo` (e.g. lower the tier maximum or raise the Holdout), run it again and show both. Show the
    `preview` (T28) numbers for the change, then revert to the original version. Use the `real-discount`
    Customer, so the flip is visible.
  - `withdraw`, "Emergency withdraw pulls outstanding Offers". The setup queues two Offers. Then
    `withdraw_outstanding` runs and shows the count and the `withdrawn` statuses. The scenario restores nothing
    else, and its Offers belong to its own Customers.
- `src/offer_engine/demo/runner.py`: a scenario may return extra result lines (the before/after Decisions, the
  preview numbers, the withdraw count) for the formatter and the live page. Add a field to `ScenarioResult`
  rather than changing existing fields: T39 reads them in parallel.
- Re-record: `AGENT_MODE=record offer-engine demo check`, then commit `demo/agent_recordings.jsonl`.

## Details
- Validation is unchanged. These scenarios exercise the existing rejection and Fallback path (ADR 0001).
- `rule-change` uses Preview impact, which takes 50–70 s on 10k Customers. Run it with a spinner line in the CLI.
  If that is too slow for a live demo, pass `parallel=True` and note the time as `Done as built`.
- The live page (T39) builds its buttons from `SCENARIOS`, so it needs no change for these.

## Tests
- `tests/demo/test_scenarios.py`, on the 300-Customer fixture with stand-ins:
  - A tampered 40% proposal is rejected and the Fallback's Offer passes.
  - The tampered caption fails the Caption Check.
  - `rule-change` leaves the Rules at their original content afterwards.
  - `withdraw` marks only its own Offers `withdrawn`.
- `tests/demo/test_scenarios_world.py` (marked `demo`): all ten pass.

## Check
```
uv run offer-engine demo reset
AGENT_MODE=replay uv run offer-engine demo run agent-breaks-rule
AGENT_MODE=replay uv run offer-engine demo check       # 10 PASS
```

## Done when
- [ ] The four scenarios run and pass; `demo check` shows 10 PASS
- [ ] The tamper wrapper is used only by scenarios
- [ ] Recordings re-committed
- [ ] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [ ] Committed: `T38: demo scenarios safety net and marketer controls`
