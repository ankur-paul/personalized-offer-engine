# Friction log

Rough edges in the working setup (skills, `CLAUDE.md`, docs, workflow) that only showed up while building. Append only; newest at the bottom.

Entry format:

```
- [YYYY-MM-DD] **<skill / file / practice>** (bug | gap | improvement | disagreement): what happened, while doing what. Why it matters. Suggested fix.
```

## Entries

- [2026-10-22] **tickets/board.py, tickets/test_board.py** (gap): with ruff 0.17's default rules, `ruff check .` reports 5 findings in the ticket tooling (unused import, `re.M` alias, `subprocess.run` without `check`, shebang on a non-executable file). Found while adding ruff in T01. Every ticket that lints the whole repo will hit them. Fix the 5 findings or add `extend-exclude = ["tickets"]` to `[tool.ruff]`.
- [2026-10-22] **tickets/T11-agent-chooser.md** (bug): T11 says to add a `validation_failures` column to `decisions` in `t11_agent_columns.sql`, but T02's `t02_core.sql` already has it, so the migration would fail with a duplicate column. Found while T09 started writing failures to it. Fix: T11 adds only `agent_output`.
- [2026-10-23] **tickets/T11-agent-chooser.md** (bug): T11 says to force the `propose_offer` tool with `tool_choice`, but Claude Opus 5.5, Sonnet 5.5 and Fable 5.1 reject forced tool choice with a 400. Found while building the agent chooser with the `claude-api` skill. A ticket that names an API option can go stale before it is built. Fix: tickets name the outcome ("exactly one tool call, schema-valid") and leave the API option to the build-time lookup that CLAUDE.md › Claude API already requires.
- [2026-10-23] **tickets/T13-generator-10k-scale.md** (improvement): T13's Scope prescribed a numpy rewrite of `simulate_day`, but profiling showed T05's code already met both budgets (83 s and 0.16 s against 5 min and 5 s). Found while profiling T13. A ticket that names the fix before anyone has measured can cost a rewrite that changes every random draw under parallel tickets. Fix: performance tickets state the budget and "profile first", and the fix is decided only if the budget is missed.
- [2026-10-23] **tickets/T14-random-past-offers.md** (bug): T14 said a past Offer controls purchases only during its 3-day validity, but Ground Truth's `p_buy` is a 7-day chance and T16 compares 7-day purchase rates. That would add about 4/7 × base to every measured Lift, most for Sure Things. T14's test also required calibration target 4, which T05 and T12's data can't meet whatever T14 does. Found while building T14. A ticket that combines numbers from two earlier tickets can disagree with both. Fix: when planning, check that each time window and rate agrees across the tickets that share it, and keep calibration asserts in the ticket that owns the tuning (T15).
