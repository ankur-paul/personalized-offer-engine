# T40 — Live engine view: outcome, truth panel, controls
**Status:** IN PROGRESS
**Prereqs:** T39 · **Branch:** t40-live-outcome-truth

## Goal
The live page shows what happens after the Decision and how good the engine's guess was:
- the Offer Card and the Customer Bot's reply;
- the buying chance and the seeded flip;
- a panel marked "Hidden from the engine" with the true chances next to Estimated Lift;
- world counters that move while the clock runs;
- Reset and Agent Replay / Live controls.

Closes the demo pass: T39 → T40, then T29 deploys it (QnA Q45, Q49, Q50, Q51).

## Scope / files
- `src/offer_engine/sim/explain.py` (simulator side; the only place the live page gets Ground Truth):
  `truth_for(conn, customer_id, offer_row | None, at) -> TruthView`. It returns the Response Class, the 7-day
  chance with no Offer, and the chance under each Offer Type at the depth the Eligible Set would allow (or the
  Offer's own depth), with `p_buy` and `buy_chance` from `sim/ground_truth.py` and `sim/world/outcomes.py`.
- `src/offer_engine/live/app.py`:
  - `GET /customers/{id}/truth` returns the `TruthView`.
  - `GET /offers/{id}/card.png` returns `offer_card.render_offer_card`.
  - `GET /counters` returns today's Decisions by Trigger, Offers sent, Claims, Redemptions, Offer spend and the
    simulated time.
  - `POST /reset` runs `demo.snapshot.reset`.
  - `GET` and `POST /agent-mode` read and set the agent mode for scenario runs in this process (`replay` or
    `live`; `live` needs `ANTHROPIC_API_KEY`).
- `src/offer_engine/live/static/`:
  - **Outcome panel**, after the Offer stage: the Offer Card image, then a chance bar from `p_base`, to `p_used`
    with the message-fit nudge labelled ("+15% for message fit, capped at ±30%"), then the flip result. Then the
    Customer Bot's reply text and Claimed, Not now or Redeemed.
  - **Truth panel**, visibly marked "Hidden from the engine: simulator only": the Response Class, then true
    chance against Estimated Lift per Offer Type, with the chosen option highlighted.
  - **Counters strip**, refreshed every 2 s.
  - **Controls**: Reset (with a confirm step on the page, not a browser dialog) and an Agent: Replay / Live
    switch showing the current mode.
  - Placement follows T39 Details › Look and feel: the counters strip and controls go in a bar above the diagram,
    and the outcome and truth panels go below the stage card and appear only after the Offer stage.

## Details
- The new panels follow T39's Look and feel rules: same colour tokens, type sizes and spacing, Glossary tooltips
  on terms such as Response Class and Estimated Lift, and no new hues. The truth panel stands apart by a tinted
  background and its label (QnA Q53).
- The pipeline and the trace still never read Ground Truth. `live/` may import `offer_engine.sim` because it's an
  entry point; the boundary test doesn't change. Add a test that `trace.py` output for a scenario holds no
  Ground Truth field names.
- Reset while a scenario runs gets `409`.
- The Live switch affects only scenario runs started from this page. The Offer Bot and Customer Bots keep their
  own `AGENT_MODE` from the environment.

## Tests
- `tests/live/test_app.py`:
  - `/customers/{id}/truth` matches `ground_truth.p_buy` for the fixture Customer.
  - `/offers/{id}/card.png` is a PNG.
  - `/counters` counts a fixture day.
  - `/reset` restores the snapshot and gets `409` while a run is going.
  - `/agent-mode` switches modes and refuses `live` without a key.
- `tests/sim/test_explain.py`: the no-Offer chance equals the base, and a Sleeping Dog's Offer chance is below its
  base.

## Check
With `start` running, on http://localhost:8502:
- Run **A Lost Cause gets a ₹0 Nudge**. The Offer Card appears, the chance bar shows about 5.3%, moved by
  message fit, and the flip shows "Not now" with the bot's reply.
- The truth panel shows Lost Cause, with free shipping's true chance above the Nudge's, and Estimated Lift
  disagreeing.
- Turn on console auto mode: the counters move.
- Press **Reset**: the simulated time goes back to 2026-12-01 00:00.

## Done when
- [ ] Outcome panel shows the Offer Card, the chance with its nudge, the flip and the bot's reply
- [ ] Truth panel shows the true chances against Estimated Lift, marked simulator-only
- [ ] Counters, Reset and Agent Replay / Live work
- [ ] The new panels follow T39's Look and feel at 1280 px and 390 px, in both themes
- [ ] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [ ] Committed: `T40: live view outcome, truth panel and controls`
