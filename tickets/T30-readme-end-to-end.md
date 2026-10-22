# T30 — README and end-to-end demo check
**Status:** TODO
**Prereqs:** T15, T27, T28, T29 · **Branch:** t30-readme-e2e

## Goal
A fresh clone plus the README gets someone to a working demo, and the full click-through works end to end on the
deployed bot. Closes the pass; mandatory (PLAN §1, §8).

## Scope / files
- `README.md`: what it does and why (Incremental Margin, not likelihood to buy); how a Decision is made (Rules →
  agent → Validation → Fallback, ADR links); quick start (`uv sync`, `offer-engine setup`, `generate`, `lift fit`,
  `personas` / `chats link-showcase`, `start`); the demo script; results headline from `offer-engine simulate`
  with the numbers; architecture diagram (three processes, SQLite, simulator boundary); tests; limits (link
  `FEATURES.md` Known limits); synthetic-data and secrets notes.
- `docs/DEMO.md`: the click-through, step by step with what should appear: console advance → Decisions with
  Binding Rules → Customer Bots receive and react → a Tester picks a Customer, `/offers`, Claims, sees the
  simulated order → Holdout Customer gets nothing → Sure Thing gets No Offer → rule change with Preview impact →
  emergency withdraw → Results page.
- `tests/test_end_to_end.py`: headless run on a 300-Customer world with a fake agent: generate → lift fit → link
  two fake chats → advance 5 days → assert Decisions from several Triggers and the Daily Sweep, Offers sent,
  Claims and Redemptions, a Holdout Customer with no Offers, every Offer passing Validation at its rule version.

## Details
- Run the click-through on the deployed host; fix small breakages in this ticket; anything bigger becomes a new
  ticket via `/tickets` and goes into PROGRESS.md "Known issues / cuts".
- Use the `unslop` skill on README and DEMO (CLAUDE.md › Docs).

## Tests
`tests/test_end_to_end.py` as above.

## Check
Follow `docs/DEMO.md` on the deployed bot and console from start to finish; every step shows what it says.

## Done when
- [ ] README covers quick start, how it decides, results and limits
- [ ] `docs/DEMO.md` click-through passes on the deployed bot
- [ ] Headless end-to-end test green
- [ ] PROGRESS.md line added; FEATURES.md up to date; `uv run pytest` green
- [ ] Committed: `T30: README and end-to-end demo check`
