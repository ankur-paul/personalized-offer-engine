# Friction log

Rough edges in the working setup (skills, `CLAUDE.md`, docs, workflow) that only showed up while building. Append only; newest at the bottom.

Entry format:

```
- [YYYY-MM-DD] **<skill / file / practice>** (bug | gap | improvement | disagreement): what happened, while doing what. Why it matters. Suggested fix.
```

## Entries

- [2026-10-22] **tickets/board.py, tickets/test_board.py** (gap): with ruff 0.17's default rules, `ruff check .` reports 5 findings in the ticket tooling (unused import, `re.M` alias, `subprocess.run` without `check`, shebang on a non-executable file). Found while adding ruff in T01. Every ticket that lints the whole repo will hit them. Fix the 5 findings or add `extend-exclude = ["tickets"]` to `[tool.ruff]`.
- [2026-10-22] **tickets/T11-agent-chooser.md** (bug): T11 says to add a `validation_failures` column to `decisions` in `t11_agent_columns.sql`, but T02's `t02_core.sql` already has it, so the migration would fail with a duplicate column. Found while T09 started writing failures to it. Fix: T11 adds only `agent_output`.
