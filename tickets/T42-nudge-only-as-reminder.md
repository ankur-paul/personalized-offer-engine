# T42 — A Nudge only when there is something to remind about
**Status:** TODO
**Prereqs:** T40 · **Branch:** t42-nudge-reminder

## Goal
A ₹0 Nudge is eligible only on the abandoned-cart and points-expiring Triggers (QnA Q56). Today the Daily Sweep
sends a Nudge to about 7,000 Customers a day, which fills the frequency cap by day 3 and blocks the paid Offers
that would follow.

## Scope / files
- `src/offer_engine/rules.py`: `eligible_set` takes the Trigger; the Nudge option is added only for
  `cart_abandoned` and `points_expiring`. Every caller passes the Trigger.
- `src/offer_engine/validation.py`: re-checks the same, so an agent's Nudge on another Trigger fails with
  `offer_type`.
- Callers: `pipeline.py`, `commands/eligible.py`, `sim/preview.py`, `sim/offline.py` and any other caller of
  `eligible_set` or `validate`.
- `GLOSSARY.md` stays as is: its Nudge definition already says this.

## Details
- Test-first (CLAUDE.md, Testing). Extend the property test: a random Nudge proposal on any other Trigger never
  passes.
- Demo: `sure-thing`, `agent-breaks-rule` and `manipulative-caption` decide on the Daily Sweep with the agent, so
  their prompts change and their recordings miss. Re-record them with `AGENT_MODE=replay offer-engine demo check`
  and a key, which records only the missing answers. `lost-cause-nudge` fires on an abandoned cart and keeps its
  Nudge. Check every scenario's expected Decision still holds.
- Update FEATURES.md's Known limits on the sweep's Nudges with the new first-day numbers.

## Tests
- `tests/test_rules.py`: a Nudge is in the Eligible Set for the two reminder Triggers only.
- `tests/test_validation.py`: a Nudge proposal on the Daily Sweep fails; the property test covers every Trigger.
- `uv run offer-engine demo check` passes.

## Check
`make reset`, then +1 day and +1 day in the console: Offers on day 2 and day 3 are mostly paid Offers or No Offer
with "nothing worth sending", and the frequency cap no longer stops most Decisions from day 3.

## Done when
- [ ] Nudges only on the two reminder Triggers, in the Rules and in Validation
- [ ] Demo scenarios re-recorded and `demo check` passes
- [ ] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [ ] Committed: `T42: Nudge only as a reminder`
