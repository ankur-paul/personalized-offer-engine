# T28 — Preview impact of a Rule change
**Status:** TODO
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

## Tests
- `tests/sim/test_preview.py`: on a 300-Customer fixture, raising the margin floor reduces Offers and cost;
  identical Rules give a zero diff; the live database file is byte-identical after a preview.

## Check
Console › Rules: change "Never discount below __% margin" from 5 to 15 → **Preview impact** → negative Offer and
cost deltas with the margin floor as the top changed Binding Rule; nothing saved until **Save**.

## Done when
- [ ] Preview impact diffs one Daily Sweep under current vs edited Rules
- [ ] The live database is untouched by a preview
- [ ] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [ ] Committed: `T28: preview impact of Rule changes`
