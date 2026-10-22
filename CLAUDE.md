## Project

**Personalised Offer Engine** decides which offer, if any, each Customer of a fictional Indian online marketplace should get, and when. Rules set by the marketing team limit every offer, and offers go out over Telegram. A discount sent to someone who would have bought anyway is lost margin, so the engine optimises Incremental Margin, not likelihood to buy. The brief requires synthetic data only, with secrets kept in `.env` and never committed.

These points are settled in `docs/adr/`. Change one only through a new ADR:

- **Pipeline** (ADR 0001): Rules compute the Eligible Set. The Claude agent picks one Offer or No Offer from it, sets its parameters and writes the message. Validation re-checks every Rule, and a rule-based Fallback runs on failure.
- **Ground Truth** (ADR 0002): Each Customer has a hidden buying-chance formula per Offer Type (Response Class is derived from it). Only the simulator reads it. If the decision pipeline reads it, that is a bug.
- **Simulation Clock** (ADR 0003): All Rules, events and expiries use simulated time, advanced from the console. Wall-clock time is used only for Telegram delivery.
- **Customer Bots** (ADR 0004): Ground Truth sets the base chance of buying; an agent may nudge it by at most ±30% for message fit; a weighted coin flip decides.
- **Offer Card** (ADR 0005): Code draws the Offer's terms from the validated Offer. The agent writes only the caption.

For everything else, follow `docs/PLAN.md` (v2, agreed). Re-read the relevant section before starting a feature; if the plan changes, record why in `docs/QnA.md` or a new ADR. Name things in code and docs with the `GLOSSARY.md` terms exactly. If a feature isn't covered by these sources, ask before building it.

## Tickets

Work is split into tickets in `tickets/`. Before you pick, start or finish a ticket, read `tickets/README.md`: it has the board, the claim rule and the ticket lifecycle. Prefix commit messages with the ticket ID (`T03: …`).

## Docs

- Record every feature you build in `PROGRESS.md`, in the same commit as the feature.
- **Append only:** add one line at the bottom of the log as `- [TNN] what was built (how to see/try it)` (`[chore]` for work outside a ticket). Never rewrite or reorder other entries.
- Parallel branches will conflict on this file; resolve by keeping **both** sides' lines.
- Note anything cut, known bugs or workarounds under "Known issues / cuts" so the demo has no surprises.
- `FEATURES.md` describes what the app does now. A commit that changes what users see or can do updates the matching bullet, and its "Known limits", in the same commit. Edit it in place; it is not a log. On a merge conflict, keep both sides' changes.
- use "/unslop" skill to write the files in a concise, clear manner while still capturing the complete information. unless the I explicitly ask for a detailed text.

- Put all the questions-answers in a grilling session in the QnA md file, under docs. its mostly for record keeping and maybe later docs generation.

## Claude API

- Look up current Claude model IDs and prices (via the `claude-api` skill) when writing agent code. Never hard-code them from memory.

## Testing

- Every feature or module you build ships with tests covering its behaviour, in the same commit.
- Changes to the Rules engine or Validation are written test-first, including the property test that random rule-breaking proposals never pass.
- Before every commit, run the full test suite once. Commit only when it is green; if it goes red, fix the cause first.

## Friction log

When building surfaces something non-obvious that is wrong, missing or debatable in a skill, this file, the docs or the workflow itself, append an entry to `FRICTION-LOG.md` in the format at its top, then carry on. It feeds improvements to the setup, not the app.

## Note

if anything comes up, which you think could be a good candidate or CLAUDE.md, ask me to put in the file.
