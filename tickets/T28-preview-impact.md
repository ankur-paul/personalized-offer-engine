# T28 — Preview impact of a Rule change
**Status:** DONE
**Prereqs:** T20, T22 · **Branch:** t28-preview-impact

## Goal
Before saving a Rule change, the marketer clicks **Preview impact** and sees what it would do to one Daily Sweep,
e.g. "+1,240 Offers, +₹38k cost". M6 (PLAN §6, QnA Q13).

## Scope / files
- `src/offer_engine/sim/preview.py`: `preview(conn, new_rules: RuleSet) -> PreviewResult`: copy the database to a
  temp file, run `daily_sweep.sweep` at the next 10:00 with the current Rules and again with `new_rules` (rules
  chooser for everyone, no agent calls), and diff: Offers sent, worst-case and expected cost, Offers by type, top
  Binding Rules that changed, Customers newly blocked or unblocked.
- `console/pages/3_rules.py`: **Preview impact** button under the form; shows
  `+1,240 Offers · +₹38,200 worst-case cost · +₹6,100 expected cost` and a small table of changes by Offer Type
  and Binding Rule. No database writes to the live file.

## Details
- Reuse T26's database-copy helper if it exists by then; otherwise write one in `preview.py` and leave a note.
- Target: under 90 s on 10k Customers; show a spinner.
- Done as built: `preview(conn, new_rules)` reuses T26's `offline.copy_db` and runs the two sweeps as two child
  processes (`python -m offer_engine.sim.preview`), each writing its summary to a JSON file. One sweep takes about
  45 s on 10k Customers, so in one process a preview took 91.5 s; in two it takes 50–70 s. Not `multiprocessing`:
  its children rerun the parent's `__main__`, which in Streamlit (and after an AppTest) is a console page.
  `parallel=False` runs both in-process (the agent test uses it).
- Done as built: raising the margin floor from 5% to 15% changes no Offer or cost on the 300-Customer fixture or the
  10k seed-7 world. The rules chooser's discounts already sit under the new limit, and a Nudge replaces any option
  the floor drops. So the "reduces Offers and cost" test raises the Holdout from 10% to 50%, a second test checks a
  25% floor takes over as Binding Rule from the loyalty-tier caps, and the Check used Holdout 10% → 20%
  (FRICTION-LOG 2026-10-24).
- Done as built: "Offers" counts every Offer the sweep makes, Nudges included. Binding Rules show by field name, as
  in the Decision log. With no edits, the button says "Nothing changed" instead of running.

## Tests
- `tests/sim/test_preview.py`: on a 300-Customer fixture, raising the margin floor reduces Offers and cost;
  identical Rules give a zero diff; the live database file is byte-identical after a preview.

## Check
Console › Rules: change "Never discount below __% margin" from 5 to 15 → **Preview impact** → negative Offer and
cost deltas with the margin floor as the top changed Binding Rule; nothing saved until **Save**.

## Done when
- [x] Preview impact diffs one Daily Sweep under current vs edited Rules
- [x] The live database is untouched by a preview
- [x] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [x] Committed: `T28: preview impact of Rule changes`
