# Tickets

Each ticket is a spec for one agent session. Read the whole ticket and the plan or spec sections it names before
writing code.

## Board: what's done, what's running, what's next

```bash
python3 tickets/board.py          # counts, every open ticket with its state, the next one to take
python3 tickets/board.py --next   # just "T03 t03-short-name" (exit 1 if nothing is ready)
python3 tickets/board.py --graph  # the prereq graph as Mermaid
```

The board is **computed, never edited**: it reads each ticket's `**Status:**` line from the default branch, every
local branch and every worktree (uncommitted edits too), so agents in parallel worktrees see each other without
merging. The newest copy of a ticket wins, except that DONE on the default branch is final. States:

| State | Meaning |
|---|---|
| DONE | `Status: DONE` committed on the default branch |
| MERGE PENDING | DONE on a branch, not merged yet; tickets that need it keep waiting |
| IN PROGRESS | a `tNN-…` branch exists (the claim), or the ticket says IN PROGRESS |
| BLOCKED / PARKED | the ticket says so, with a reason |
| READY | TODO and every prereq is DONE on the default branch |
| WAITING | TODO with prereqs not DONE on the default branch yet |
| DROPPED | won't be built; never counts as done |
| SPLIT | a container whose pieces (`T07a`, `T07b`, …) hold the work; done when they are |

## Rules for agents

1. **Pick:** run the board and take **Next** (the lowest-numbered READY ticket). Never take BLOCKED, PARKED or
   another agent's IN PROGRESS ticket. A SPLIT ticket is never taken; its pieces are.
2. **Claim:** `git branch <the ticket's **Branch:** name> <default branch>`. Git refuses if the branch already
   exists, so only one agent wins; if it fails, run the board again and take the next ticket. Then work on that
   branch (or `git worktree add ../<repo>-tNN <branch>`), and set `**Status:** IN PROGRESS` in the first commit.
3. **Read:** the ticket's Scope and Done when are the spec; ask the user before going beyond them. Decisions
   shared by several tickets are in `docs/PLAN.md` (its "Assumed" section too), `GLOSSARY.md` and `docs/adr/`. Shared types change only in a ticket whose Scope
   says so.
4. **Finish:** first merge the default branch into your ticket branch, resolve any conflicts and rerun the tests:
   tickets run in parallel, so another one may have changed the same files since you branched. Then, in the commit
   that completes the ticket, set `**Status:** DONE`, tick the checklist, and note
   anything built differently from the ticket under Details as `Done as built: …`. Update the project's changelog
   or feature docs if it keeps them. If this is the last open piece of a SPLIT ticket, tick the container's Done
   when items too. Other tickets count it as done once it is merged into the default branch.
5. **Too big:** if the ticket won't fit in your session, don't split it yourself. Commit what you have, set
   `**Status:** BLOCKED (too big: <what to split off>)` and tell the user, who splits it with `/tickets`.
6. **Stuck:** `**Status:** BLOCKED (reason)`, e.g. `BLOCKED (needs human: user test)`. Shelved on purpose:
   `**Status:** PARKED (reason)`.
7. **Ticket headers** must parse; the board lists any that don't under *Problems*:
   - `# TNN — Title`; a piece of a split ticket is `# TNNa — Title`
   - `**Status:** TODO | IN PROGRESS | BLOCKED (reason) | PARKED (reason) | SPLIT | DROPPED (reason) | DONE`
   - `**Prereqs:** T01, T02 · **Branch:** tNN-short-name`. Prereqs are whole tickets or `—`; put optional or
     partial dependencies in the ticket text. A prereq that only orders two tickets sharing a hot spot says why
     under Details.

Don't add a hand-written status table or ticket index here: it would conflict on every parallel branch and go
stale. The board and `--graph` are the index.

## Ticket template

```md
# TNN — Title
**Status:** TODO
**Prereqs:** — · **Branch:** tNN-short-name

## Goal
## Scope / files
## Details
## Tests
## Check
## Done when
- [ ] …
- [ ] Committed: `TNN: …`
```
