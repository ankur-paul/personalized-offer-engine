# T30 — README and end-to-end demo check
**Status:** TODO
**Prereqs:** T15, T27, T28, T29, T38 · **Branch:** t30-readme-e2e

## Goal
A fresh clone plus the README gets someone to a working demo, and the full click-through works end to end on the
deployed bot. Closes the pass; mandatory (PLAN §1, §8).

## Scope / files
- `README.md`: what it does and why (Incremental Margin, not likelihood to buy); how a Decision is made (Rules →
  agent → Validation → Fallback, ADR links); quick start (`uv sync`, `offer-engine setup`, `generate`, `lift fit`,
  `personas` / `chats link-showcase`, `start`); the demo script; results headline from `offer-engine simulate`
  with the numbers; architecture diagram (three processes, SQLite, simulator boundary); tests; limits (link
  `FEATURES.md` Known limits); synthetic-data and secrets notes.
- `docs/DEMO.md`: the click-through, step by step with what should appear, driven from the live engine page
  (T39, T40) after **Reset**, with `AGENT_MODE=replay`: each of the ten scenarios from `offer-engine demo list` in
  order (saving margin → hard limits → safety net → marketer controls), what each proves, and what the stages,
  outcome and truth panel show; then one Tester exchange on a phone (`/start`, pick a Customer, `/offers`, Claim,
  simulated order); then the console's Results page. Start with `offer-engine demo check` as the pre-demo test.
  Ordering prereq T38: DEMO.md scripts T38's scenarios.
- `tests/test_end_to_end.py`: headless run on a 300-Customer world with a fake agent: generate → lift fit → link
  two fake chats → advance 5 days → assert Decisions from several Triggers and the Daily Sweep, Offers sent,
  Claims and Redemptions, a Holdout Customer with no Offers, every Offer passing Validation at its rule version.

## Details
- Run the click-through on the deployed host; fix small breakages in this ticket; anything bigger becomes a new
  ticket via `/tickets` and goes into PROGRESS.md "Known issues / cuts".
- Use the `unslop` skill on README and DEMO (CLAUDE.md › Docs).
- `README.md` was written on main ahead of this ticket (2026-10-27). Still to add: the deploy (T29), a link to
  `docs/DEMO.md`, the architecture diagram, and fresh `simulate` numbers if the run is repeated.

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
