# T33 — Stretch: send-time choice
**Status:** TODO
**Prereqs:** T10, T11, T21 · **Branch:** t33-send-time

## Goal
*Stretch:* the agent chooses when to send, now or at hour H within the allowed send hours and maximum delay, and the
Offer is delivered when the Simulation Clock reaches it. M7 (PLAN §3.5 step 2, QnA Q22).

## Scope / files
- `src/offer_engine/choosers/agent_chooser.py`: add `send_hour` (int or `"now"`) to the tool schema; give the
  agent the Customer's observed active hours (from session events) and the `send_window`; convert to `send_at`.
- Rules chooser keeps the start of `send_window`.
- Validation already rejects `send_at` outside `send_window` (T07); add tests for agent-chosen hours.
- `console/pages/2_decisions.py`: show `send_at` and "scheduled" for Offers not yet sent.

## Details
- Delivery already waits for `send_at ≤ clock.now()` (T10, T17); auto mode in the console advances by day, so
  make sure hourly processing in `day_step.advance` lets the Offer Bot deliver mid-day Offers in order.

## Tests
- `tests/test_agent_chooser.py`: send hour inside the window → `send_at` set; outside → Fallback with
  `send_at_outside_window`.

## Check
Trigger at 08:00 simulated for a Customer whose sessions cluster in the evening → Decision with `send_at` 19:00;
the card arrives only after the clock passes 19:00.

## Done when
- [ ] The agent chooses a send hour within the allowed window, validated
- [ ] Scheduled Offers are delivered when the clock reaches `send_at`
- [ ] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [ ] Committed: `T33: agent send-time choice`
