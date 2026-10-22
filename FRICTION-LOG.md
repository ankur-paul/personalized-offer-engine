# Friction log

Rough edges in the working setup (skills, `CLAUDE.md`, docs, workflow) that only showed up while building. Append only; newest at the bottom.

Entry format:

```
- [YYYY-MM-DD] **<skill / file / practice>** (bug | gap | improvement | disagreement): what happened, while doing what. Why it matters. Suggested fix.
```

## Entries

- [2026-10-22] **tickets/board.py, tickets/test_board.py** (gap): with ruff 0.17's default rules, `ruff check .` reports 5 findings in the ticket tooling (unused import, `re.M` alias, `subprocess.run` without `check`, shebang on a non-executable file). Found while adding ruff in T01. Every ticket that lints the whole repo will hit them. Fix the 5 findings or add `extend-exclude = ["tickets"]` to `[tool.ruff]`.
- [2026-10-22] **tickets/T04-bot-to-bot-spike.md** (gap): T04's Prereqs list only T02, but its Check and two Done-when items need real bot tokens in `.env`, which only `offer-engine setup` (T03, blocked on a human) provides. The board showed T04 as ready, and it could only end BLOCKED on the same human step. A ticket whose Check needs credentials should name the human step as a prereq, or the board should flag tickets whose Check needs a human.
