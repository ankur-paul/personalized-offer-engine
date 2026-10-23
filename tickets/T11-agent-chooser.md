# T11 — Agent chooser: Claude picks from the Eligible Set and writes the caption
**Status:** DONE
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
- Done as built: `tool_choice` is `auto` with `strict: true` on the tool, not forced. Forcing a tool returns a 400 on
  Claude Opus 5.5, Sonnet 5.5 and Fable 5.1. A reply without a `propose_offer` call, a refusal or a `max_tokens`
  stop raises `AgentError`, so the rules chooser takes over.
- Done as built: `params` lists all five parameter names (`pct`, `cap`, `amount`, `min_basket`, `multiplier`) and
  the agent sends null for the ones its option doesn't take, because strict schemas need fixed properties. The
  chooser drops the nulls. The schema has no length limits (strict mode doesn't support them), so the Caption
  Check catches long captions and the chooser cuts the reason to 200 characters.
- Done as built: only `agent_output` is new in `t11_agent_columns.sql`; `validation_failures` was already in
  `t02_core.sql`.
- Done as built: `make_agent_chooser` returns an `AgentChooser` whose `last_output` holds the raw tool input. The
  pipeline reads it with `getattr` and stores it on the Decision, including when the proposal failed.
- Done as built: `default_chooser(state, trigger)` also takes the Trigger, so the prompt can name it. The client
  has `max_retries=0` and each call a 20 s timeout, effort `low` and `cache_control` on the system prompt. With a
  key but no `OFFER_AGENT_MODEL`, the Decision falls back with `chooser_error: RuntimeError: OFFER_AGENT_MODEL is
  not set in .env`.
- Done as built: the prompt shows the Trigger and send time, the Customer's profile, past Offers, event counts
  and the latest 20 events other than sessions and views from the last 90 days, up to 12 recent products (the
  only allowed featured products), each category's margin and basket, and the Eligible Set with ranges, Binding
  Rules, worst-case cost and Estimated Lift (or the prior's guess until T16).
- Done as built: `trigger` and `decisions` print the agent's rejected proposal on a Fallback Decision. An autouse
  fixture in `tests/conftest.py` keeps the API key from the pipeline in every test not marked `live`.
- Done as built: the live test and the `chooser=agent` half of the Check were not run, because this environment
  has no `ANTHROPIC_API_KEY`. The `ANTHROPIC_API_KEY=bad` half gives `chooser=fallback` with
  `chooser_error: AuthenticationError: … 401`. `chats link` comes with T10; until then, add a `chats` row by hand.

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
- [x] Chat-attached Customers are decided by the agent; others by the rules chooser
- [x] Caption Check runs inside Validation
- [x] Invalid proposals and API failures fall back, with failures stored on the Decision
- [x] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [x] Committed: `T11: agent chooser with Caption Check and Fallback`
