# T44 — Live view: agent badge, Agent filter and Customer Bot reactions on playback
**Status:** IN PROGRESS
**Prereqs:** T43 · **Branch:** t44-agent-badge-bot-reactions

## Goal
In the live view you can't tell which Decisions used the agent, and you can't see how a Customer Bot reacted to
an Offer unless you just ran a scenario. Only 35 of about 54,000 Decisions in `data/offer_engine.db` used the
agent, so scanning the ticker for them doesn't work. This ticket marks agent Decisions in the ticker, adds a
filter to list only those, and fills "What the Customer did" when a Decision is played back from the log.

## Scope / files
- `src/offer_engine/commands/_format.py`: `fetch_decisions` takes `choosers`, a list of `Chooser` values to keep.
- `src/offer_engine/live/app.py`: `/decisions/latest` rows gain `chooser` and `reacted`, and the route takes
  `?chooser=agent`. A new route `GET /offers/{offer_id}/outcome`.
- `src/offer_engine/live/static/app.js`, `style.css`, `index.html`.
- No change to the pipeline, the trace format, `roleplay.py` or the scenarios.

## Details
1. **Agent badge.** Each ticker row shows a chip after the outcome: "Agent" when `chooser` is `agent`, and
   "Fallback" when it is `fallback` (the agent answered and Validation rejected it, or the call failed). A `rules`
   row has no chip. When `reacted` is true (the Offer has a `sim_bot_responses` row), line 2 ends with "· Customer
   Bot replied".
2. **Agent filter.** A two-button switch under the "Latest Decisions" heading: "All" and "Agent". "Agent" calls
   `/decisions/latest?chooser=agent`, which keeps `agent` and `fallback` rows, since the LLM was called in both.
   The server filters, so the 20 rows are the newest agent Decisions and not the agent ones among the newest 20.
   The page remembers the choice in `localStorage` (wrapped in try/catch). Any other `chooser` value gets a 422.
3. **Reactions on playback.** `GET /offers/{offer_id}/outcome` returns the outcome in the shape `result_json`
   already uses (`p_base`, `fit`, `p_used`, `buys`, `claims`, `reply`, `bot_reply`):
   - Customer Bot: from `sim_bot_responses`. `bot_reply` is null, since the Offer Bot's answer isn't stored.
   - Customer without a chat: from `sim_offer_fates`. `p_base` = `p_used`, `fit` and `reply` are null, and
     `claims` is `buys or claim_at is not null`.
   - No reaction yet (a Customer Bot whose card hasn't arrived, or an Offer still queued): `{"outcome": null}`.
   - Unknown Offer: 404.

   On playback, `outcomePanel` fetches it and draws the steps as it does after a scenario run. With no outcome, it
   says "No reaction yet: the Customer hasn't answered this Offer." This replaces "The chance, the flip and the
   replies show for a scenario run." The route reads simulator tables, as `/customers/{id}/truth` does; the
   pipeline and the trace still don't.
4. **No new page.** There are 7 Customer Bots, 4 reactions in the dev database and none in the demo snapshot, so
   a page of their own would be nearly empty. A reaction ends one Decision, and the live view already has its slot
   below the Offer stage. Record this in `docs/QnA.md` under the latest round.

### Look and feel
Follows T39's and T43's Look and feel with these changes:
- **Chip:** 14 px text, 0 8 px padding, 8 px radius, on line 1 after the outcome with 8 px between them. "Agent"
  uses `--accent` text on `--accent-soft`. "Fallback" uses `--muted` text with a 1 px `--muted` border and no fill.
  The chip's `title` says "Chosen by the agent" or "The agent's answer failed Validation; the rules chooser
  decided".
- **"Customer Bot replied":** plain 14 px `--muted` text on line 2, with the glossary underline on "Customer Bot".
- **Filter:** reuses the `.switch` style of the Agent switch (`aria-pressed`), 8 px below the heading and 8 px
  above the list.
- **Empty "Agent" list:** "No agent Decisions yet. The agent decides for Customers with a chat: run a scenario or
  advance the clock." in 14 px `--muted`.
- No new hues; spacing in multiples of 8 px; both themes.

## Tests
In `tests/live_view/test_app.py` and the `_format` tests:
- `fetch_decisions(choosers=[...])` keeps only those choosers, newest first, and `last` counts after the filter.
- `/decisions/latest` rows carry `chooser` and `reacted`. `?chooser=agent` returns only `agent` and `fallback`
  rows. `?chooser=bogus` returns 422.
- `/offers/{id}/outcome`: a Customer Bot reaction returns its stored `p_base`, `fit`, `p_used`, `buys`, `claims`
  and `reply`; a fate for a Customer without a chat returns `fit` null and `p_base` = `p_used`; an Offer with
  neither returns `{"outcome": null}`; an unknown ID returns 404.
- The badge, filter and panel are checked by hand under Check; the page has no JS test harness (T43).

## Check
`uv run offer-engine demo reset && AGENT_MODE=replay uv run offer-engine start`, open http://localhost:8502 at
1280 px.
- Run **A Lost Cause gets a ₹0 Nudge**. Its ticker row shows the "Agent" chip and "· Customer Bot replied".
- Run **Validation rejects a rule-breaking proposal**. Its row shows "Fallback".
- Click "Agent": only chipped rows are left. Reload: "Agent" is still selected.
- Play the Lost Cause row from the ticker. "What the Customer did" shows the chance meter, the fit nudge and the
  Customer Bot's reply.
- Play a `rules` row with an Offer to a Customer without a chat: the panel shows the chance and the flip, with
  "No Customer Bot, so no message-fit nudge".
- Repeat in dark theme.

## Done when
- [ ] Ticker rows show the Agent or Fallback chip and "Customer Bot replied"
- [ ] "All / Agent" filter, filtered on the server, remembered across reloads
- [ ] Playback fills "What the Customer did" from stored reactions and fates
- [ ] QnA entry records why reactions stay on the live view and get no page of their own
- [ ] Look and feel holds at 1280 px in both themes
- [ ] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [ ] Committed: `T44: agent badge and Customer Bot reactions in the live view`
