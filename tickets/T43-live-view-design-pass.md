# T43 — Live view design pass: playback in view, clear endings, plain labels
**Status:** DONE
**Prereqs:** — · **Branch:** t43-live-view-design-pass

## Goal
A design critique of the live engine view (http://localhost:8502, 2026-10-26, at 1280 px in both themes) found that the page's main job, watching a Decision play, often happens out of sight or ends ambiguously.
This ticket fixes that and tidies the labels a judge reads. It adds no new data, routes or charts. Desktop only:
mobile layout is out of scope; leave the existing narrow-screen behaviour as it is.

## Scope / files
- `src/offer_engine/live/static/app.js`, `style.css`, `index.html`, `world.css` and `world.js` as needed.
- `src/offer_engine/live/app.py` only if a ticker row needs the Customer's name (see Details).
- No change to `scenarios.py`, the trace format or any pipeline module.

## Details
Critique findings this ticket fixes, worst first:

1. **Playback happens off screen.** The ticker sits below 11 scenario buttons, about 1,500 px down at 1280 px.
   Clicking a row there plays the trace at the top of the page, so the viewer sees nothing change. Only the header
   status ("Decision #54388: done", 14 px grey, top right) shows it worked. Fix: when a ticker row or scenario
   starts playing, scroll the diagram into view (`block: "start"`, smooth unless `prefers-reduced-motion`).
2. **The ticker is hard to reach.** Put Latest Decisions at the top of the rail, above the scenario groups, so
   both of the page's entry points sit above the fold. This changes T39's Look and feel, which put the ticker
   below the scenarios; record it in `docs/QnA.md`.
3. **A No Offer ends on a green "Offer" node.** Decision #54388 stops at Checks (red ✕) and the last node is still
   a green ✓ "Offer". It reads as "an Offer was sent". Fix: when the Decision is No Offer, the last node's label
   becomes "No Offer" and it takes the grey "stopped" style with a "–" badge, not green ✓. Stages skipped after a
   stop get dashed borders and dashed arrows, so skipped and not yet reached look different.
4. **"stage 4" doesn't match the diagram.** The card eyebrow numbers trace stages ("Decision #54388 · stage 4"),
   while the Offer node is 8th in the diagram. Drop the number: "Decision #54388 · Offer stage".
5. **Raw keys in plain-word text.** The Checks card shows `opt_out`, `holdout_pct` and
   `cooldown_days_after_redemption` in monospace beside each Rule's name. The Offer card says "No Offer: holdout
   (holdout_pct)" and "Chosen by rules". Fix: show the Rule's name only ("Stopped by the Holdout"). Move the key into
   the row's `title` attribute for anyone debugging. Show "Chosen by: rules chooser" or "Chosen by: agent", as
   the Who decided card already says.
6. **The Offer card repeats itself.** It shows "No Offer: …" as the summary and then "No Offer" again as a
   heading. Keep one.
7. **Ticker rows are hard to scan.** Each row reads "#54388 · 2026-12-06 10:00 · C04200 · daily sweep / No
   Offer". Lead with the outcome (bold, ✓ or –), then the Customer's name if `/decisions/latest` can return it
   (add `customer_name` there), then the Trigger and the time as "6 Dec, 10:00", the format the charts use. Shorten
   rows from 81 px to about 56 px.
8. **Too many dotted underlines.** Every "Offer", "Customer" and "Decision" in every sentence is underlined, so
   the Glossary terms that matter don't stand out. Underline only a term's first use in each card, and never in a
   heading (the 28 px "Offer" and "No Offer" headings look like links).
9. **The counters strip is uneven.** "Decisions today" runs a long inline breakdown ("cart abandoned 40 · daily
   sweep 9823 · …") that pushes "Offers sent today" to the far right on its own. The breakdown counts lack
   grouping (9823, not 9,823). Fix: lay out the six counters on one grid of three columns. Move the Trigger breakdown under a "by Trigger" `<details>`. Use Indian grouping everywhere.
10. **A risky control sits among the stats.** Reset is beside the Replay/Live switch, inside the stats card. Move
    the Agent switch and Reset to their own row below the counters, separated by a rule, with Reset styled as a
    secondary danger button (red text, no fill). It already asks before it acts; keep that.
11. **The two top chart cards end at different heights.** "Offers sent, Claimed and Redeemed" leaves about 120 px
    of empty card under its content, beside the taller Decisions chart. Align the content to the top and let the
    card shrink, or stretch the funnel bars to fill. Don't leave a blank band.
12. **Off-scale type.** One element renders at 18 px. Use the 14/16/20/28 scale only.

What works and must stay: the grouped scenario buttons with their `proves` subtitles; the ✓/✕ symbols beside the
colour; the tinted "Hidden from the engine: simulator only" panels; the "Show table" view under every chart; text
contrast passes 4.5:1 throughout in light mode (checked); both themes.

Done as built:
- `customer_name` comes from the Persona Cards (`personas/`); a Tester's copy takes its source's name. Only the showcase
  Customers have cards, so most rows show the Customer ID.
- The page rewrites two summaries from the stage's data: Checks ("Stopped by the Holdout", "Every check passed") and a
  No Offer ("Stopped by the …", else the reason without its `No Offer:` prefix and rule key). The trace's own summary is
  the paragraph's `title`. An Offer's card drops the trace summary, which repeated the facts below it, and names the
  Binding Rule in words with the key as its `title`.
- A No Offer's card has "No Offer" as its heading and a "– Nothing sent" chip; the 20 px "No Offer" line is gone.
- Skipped stages are a new `passed` node state, separate from `skip` (a stage that ran and did nothing, such as Agent for
  a Customer without a chat), which keeps its "–" badge.
- The world charts' headings lost their tooltips under the heading rule; each term keeps one in the card's text.
- Item 12: after these changes no element renders at 18 px. A scan of every stage card and panel at 1280 px found only
  14, 16, 20 and 28 px, but which element was 18 px before wasn't identified.
- The Eligible Set table and its Dropped list still show rule keys in `code`. They weren't in the critique's list.
- Checked on a copy of the live database served on port 8503 after the page's Reset, at 1280 px in both themes, not with
  `demo reset` on the live database.

### Look and feel
Follows T39's Look and feel (and T41's chart palette) with these changes:
- **Rail order:** Latest Decisions (5 rows, "Show 20"), then the scenario groups.
- **Ticker row:** two lines, 8 px vertical padding. Line 1 has the outcome in bold 14 px with its symbol, then the
  Customer's name. Line 2 has the Trigger and time, 14 px muted. The selected row keeps the accent border.
- **End node:** for No Offer, the label is "No Offer" with a grey border, a "–" badge and no fill. Skipped stages
  get a 1 px dashed border with dashed arrows into them, in the muted grey.
- **Counters:** a 3-column grid with 16 px gaps. The label is 14 px muted, the
  number 20 px semibold, and the "since 1 Dec" line 14 px muted. Controls go in their own row with 16 px above, a
  1 px top border and 8 px gaps between buttons.
- **Reset:** a 40 px tall button with a 1 px border in `--bad` and `--bad` text.
- **Glossary underline:** first use per card only; none in `h2` or `h3`.
- No new hues; spacing in multiples of 8 px.

## Tests
- `tests/live_view/`: if `/decisions/latest` gains `customer_name`, a test that each row carries it.
- Page behaviour (scroll into view, end-node label, underline rule) is checked by hand under Check. The page has no
  JS test harness, and adding one is out of scope.

## Check
`uv run offer-engine demo reset && AGENT_MODE=replay uv run offer-engine start`, open http://localhost:8502 at
1280 px.
- The ticker shows above the scenarios without scrolling. Click a ticker row: the page scrolls to the diagram and
  the trace plays in view.
- Play a holdout Decision: Checks is red ✕, Eligible Set to Validation are dashed, and the last node reads "No
  Offer" in grey. No raw rule keys show; hovering a check row shows its key.
- Run **A Customer a discount moves gets one**: the last node reads "Offer", green ✓.
- The counters sit on an even grid; Reset is on its own row in red outline.
- Repeat in dark theme.

## Done when
- [x] Ticker and scenario playback scroll the diagram into view
- [x] Ticker moved to the top of the rail, with rows led by the outcome and name; QnA entry records the change
- [x] No Offer ends on a grey "No Offer" node; skipped stages are dashed
- [x] Rule keys, "stage N" and "Chosen by rules" replaced with plain words
- [x] Glossary underline on first use per card only
- [x] Counters on a grid; controls on their own row; top chart cards have no blank band
- [x] Look and feel holds at 1280 px in both themes
- [x] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [x] Committed: `T43: live view design pass`
