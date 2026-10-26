# T41 — Live view: world charts and running totals
**Status:** DONE
**Prereqs:** T40 · **Branch:** t41-world-charts

## Goal
The live page shows what the whole world has done since the clock start, so a judge can see at a glance where Offers
go and why most Decisions are No Offer (QnA Q54, Q55):
- Decisions per simulated day: Offers by kind and No Offer by reason;
- the funnel (sent → Claimed → Redeemed) and orders per Customer against the Holdout;
- Offers by hidden Response Class, marked "Hidden from the engine";
- who decided (agent, rules, Fallback) and what each chat-attached Customer got.

The header counters also show the total since the clock start, so they no longer drop to 0 at each simulated
midnight.

## Scope / files
- `src/offer_engine/sim/world_stats.py` (simulator side, as it reads Response Class): `world_stats(conn, now,
  rules) -> dict`, JSON-ready, with `days`, `funnel`, `holdout`, `truth`, `choosers` and `chats`. Reuses
  `sim/live_metrics.py` (`funnel`, `holdout_comparison`). Tester copies are left out, as in `live_metrics`.
- `src/offer_engine/live/app.py`: `GET /world` returns `world_stats`; `GET /counters` adds `since_start` with the
  same fields as today's.
- `src/offer_engine/live/static/world.js`: an ES module exporting `mountWorld(root, options)`. It fetches `/world`,
  draws the four charts as inline SVG and refreshes every 5 s while the tab is visible. It depends on no other page
  script; `options.terms(text)` may add Glossary tooltips.
- `src/offer_engine/live/static/world.css`: every rule scoped under `.world`, reading the page's colour tokens.
- `src/offer_engine/live/static/index.html`: a `<section id="world">` below the panels, mounted from a module script.
- `src/offer_engine/live/static/app.js`: the counter tiles show "N since 1 Dec" beneath today's number.

To move the charts to another page: serve `/world`, include `world.js` and `world.css`, and call `mountWorld`.

## Details
- **Decisions per day:** one stacked column per simulated day since the clock start, in five groups: Paid Offer,
  Nudge, No Offer: nothing worth sending (no Binding Rule), No Offer: frequency cap, No Offer: other Rules (Holdout,
  Opt-out, cooldown, Fatigue Pause, signup, budget). The tooltip and the table list every Offer Type and Binding
  Rule behind the groups.
- **Funnel:** horizontal bars for Offers sent, Claimed and Redeemed, labelled with the count and the share of sent.
  Beside it: Offer spend, and orders per Customer outside and inside the Holdout.
- **Who got what:** per Response Class, its share of Customers next to its share of paid Offers, and the spend on
  Sure Things. If the engine targeted well, Persuadables' share of paid Offers would be above their share of
  Customers. The panel uses T40's tint and "Hidden from the engine: simulator only" label.
- **Who decided:** Decisions by chooser as stat tiles, a line saying the agent decides only for the N chat-attached
  Customers, and one row per chat-attached Customer: Persona Card name and case, Decisions, Offers and the latest
  Decision.
- The pipeline still never reads Ground Truth; `live/` and `sim/` are entry-point and simulator code.
- Done as built: the chat-attached Customers' Decisions are read in one pass, as `decisions` has no index on
  `customer_id`; a per-row subquery took 21 s on 10k Customers, the whole `/world` takes about 0.3 s. Testers'
  copies are left out of the charts but listed under Who decided. A refresh redraws only when `/world` returns
  different numbers, so hover and focus stay put. `app.js` fires a `glossary` event once the Glossary loads, and
  the module redraws so its titles get the tooltips. Checked with headless Chrome screenshots at 1280 px and 390 px
  in both themes; hover was not tried with a mouse.

### Look and feel
Follows T39's Look and feel (type sizes, 8 px spacing, cards, tokens, both themes, 1280 px down to 390 px), with
one exception: chart marks need identity colours, so the charts get their own categorical palette, used for chart
marks and their legend swatches only, never for text or status:

| Slot | Light | Dark |
|---|---|---|
| 1 | `#2a78d6` | `#3987e5` |
| 2 | `#eb6834` | `#d95926` |
| 3 | `#1baf7a` | `#199e70` |
| 4 | `#eda100` | `#c98500` |
| 5 | `#e87ba4` | `#d55181` |

The palette passes the dataviz validator in both modes (adjacent CVD ΔE 9.1 light, 8.4 dark). Three light slots sit
below 3:1 against the card, so every chart has a legend and a table view.
- **Layout:** a section titled "The world so far" below the panels, with the four charts as cards in two columns
  from 1024 px and one column below it.
- **Marks:** bars at most 24 px thick with a 4 px rounded end, a 2 px gap between stacked segments, solid 1 px
  gridlines one step off the surface. Values are labelled selectively: column totals, funnel bars, not every
  segment.
- **Hover:** each bar or segment shows its group and value on hover and keyboard focus. Tooltips never gate: every
  chart has a "Show table" toggle with the same numbers.
- **Numbers:** rupees as `₹1,23,456`, shares to one decimal, counts with Indian grouping.
- **Refresh:** a refresh keeps the previous render until the new one is ready; no flash or layout jump.

## Tests
- `tests/sim/test_world_stats.py` on the 50-Customer world: day groups add up to the day's Decisions; the funnel
  matches `live_metrics.funnel`; Response Class shares sum to 1; choosers add up; Tester copies are left out.
- `tests/live_view/test_app.py`: `/world` returns every section; `/counters` has `since_start`, which counts the
  days before today too.

## Check
With `start` running, on http://localhost:8502: the four charts show the world. Advance the clock a day in the
console and watch the charts gain a column. The header's "since 1 Dec" totals keep their value past simulated
midnight. Check 1280 px and 390 px, light and dark.

## Done when
- [x] Four charts with legends, hover and table views, on the live page
- [x] Counters show today and since the clock start
- [x] Charts move with the clock and follow Look and feel in both themes at 1280 px and 390 px
- [x] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [x] Committed: `T41: live view world charts and running totals`
