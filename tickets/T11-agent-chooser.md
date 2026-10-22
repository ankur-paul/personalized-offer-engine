# T11 — Agent chooser: Claude picks from the Eligible Set and writes the caption
**Status:** TODO
**Prereqs:** T08, T09 · **Branch:** t11-agent-chooser

## Goal
For chat-attached Customers, Claude picks one Offer or No Offer from the Eligible Set, sets its parameters and
featured products, and writes the caption and a short reason; Validation (now including the Caption Check)
re-checks it and the rules chooser takes over on failure or outage. M3 (PLAN §3.5 step 2–4; ADR 0001, 0005).

## Scope / files
- `src/offer_engine/choosers/agent_chooser.py`:
  `make_agent_chooser(client, model: str) -> Callable[[EligibleSet, CustomerState, Catalog, RuleSet], Proposal]`.
  - One Messages API call with a single tool `propose_offer` whose input schema is: `option_index` (int, or -1
    for No Offer), `params` (object), `featured_product_ids` (≤2), `caption` (≤280 chars), `reason` (≤200 chars).
    Force the tool with `tool_choice`.
  - Prompt: the business goal (Incremental Margin, cheapest Offer that captures most Lift, No Offer is fine), the
    Eligible Set (index, type, category, ranges, Binding Rules, worst-case cost, Estimated Lift), a summary of the
    Customer's observable profile and last 90 days of events, the Trigger, and caption rules mirroring T08 (no
    numbers, no deadlines, no urgency, no promises; code draws the terms). Put the static part in a cached system
    prompt.
  - `send_at` is always the start of `send_window` (send-time choice is T33).
  - Timeout 20 s; any API error raises so the pipeline falls back.
- `src/offer_engine/pipeline.py`: change **only** `default_chooser(state)`: agent chooser when `state.chat` is set
  and `ANTHROPIC_API_KEY` is configured, else the rules chooser; and pass `caption_check.check` as
  `caption_checker` to `validate`. Record `chooser=agent` when the agent's proposal passed, `fallback` otherwise.
- Store the agent's raw tool input and Validation failures on the Decision (add `agent_output` and
  `validation_failures` columns in `schema/t11_agent_columns.sql`).

## Details
- Look up the current model IDs and prompt-caching usage with the `claude-api` skill; read them from
  `OFFER_AGENT_MODEL` in `.env`, never hard-code (CLAUDE.md › Claude API).
- The agent never sees Ground Truth or `sim_*` data (ADR 0002); the boundary test covers `choosers`.
- Featured products must come from the Customer's own recent events (Validation enforces).

## Tests
- `tests/test_agent_chooser.py` with a fake client returning canned tool inputs: valid → `chooser=agent`; param out
  of range → `fallback` with failures stored; caption with a number → `fallback` (`number_mismatch`); client
  raises/times out → `fallback`; `option_index=-1` → No Offer by agent.
- `tests/test_agent_prompt.py`: the prompt contains every option and no `sim_` field names.
- `tests/test_agent_live.py` marked `live`: one real call returns a parseable proposal.

## Check
`uv run offer-engine chats link C00042 --bot @<customer bot>`; `uv run offer-engine trigger cart-abandoned C00042`
→ Decision shows `chooser=agent`, the agent's reason, and a caption; with `ANTHROPIC_API_KEY=bad` the same command
shows `chooser=fallback`. `uv run pytest -m live tests/test_agent_live.py` passes with a real key.

## Done when
- [ ] Chat-attached Customers are decided by the agent; others by the rules chooser
- [ ] Caption Check runs inside Validation
- [ ] Invalid proposals and API failures fall back, with failures stored on the Decision
- [ ] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [ ] Committed: `T11: agent chooser with Caption Check and Fallback`
