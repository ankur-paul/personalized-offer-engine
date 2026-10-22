# Friction log

Rough edges in the working setup (skills, `CLAUDE.md`, docs, workflow) that only showed up while building. Append only; newest at the bottom.

Entry format:

```
- [YYYY-MM-DD] **<skill / file / practice>** (bug | gap | improvement | disagreement): what happened, while doing what. Why it matters. Suggested fix.
```

## Entries

- [2026-10-22] **tickets/board.py, tickets/test_board.py** (gap): with ruff 0.17's default rules, `ruff check .` reports 5 findings in the ticket tooling (unused import, `re.M` alias, `subprocess.run` without `check`, shebang on a non-executable file). Found while adding ruff in T01. Every ticket that lints the whole repo will hit them. Fix the 5 findings or add `extend-exclude = ["tickets"]` to `[tool.ruff]`.
- [2026-10-22] **tickets/T03-setup-script.md** (gap): the ticket asks the agent to "verify [the BotFather menu path] when building this ticket", but an agent has no Telegram account, and Telegram's docs (core.telegram.org/api/bots/bot-to-bot) name Bot-to-Bot Communication Mode without a menu path. The step can't be done in the session, so the ticket ends BLOCKED on a human check. Tickets that need a human to look at a third-party UI should put that under Check, not Details, so the agent doesn't plan around doing it.
