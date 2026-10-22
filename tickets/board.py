#!/usr/bin/env python3
"""Ticket board, computed from the ticket files on every branch and worktree, so it is never stale.

    python3 tickets/board.py           # the whole board
    python3 tickets/board.py --next    # the next ticket to claim, e.g. "T15 t15-contract" (exit 1 if none)
    python3 tickets/board.py --graph   # the prereq graph as Mermaid

Each ticket's own **Status:** line is the source of truth (rules in tickets/README.md). The board reads that line
from the default branch, from every local branch and from every worktree, uncommitted edits included. The most
recently changed copy wins, except that DONE on the default branch is final. A local branch named tNN-… claims
ticket TNN.

A ticket that turned out too big is SPLIT into pieces TNNa, TNNb, … (one level only). The split ticket is a
container: nobody claims it, and it counts as done once every piece is DONE or DROPPED and at least one is DONE.
Other tickets depend on the container, never on a piece; pieces may depend on each other.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

MAIN_OVERRIDE: str | None = None  # set this to force the default branch, e.g. "trunk"
MAIN = "main"  # the default branch; main() detects it unless MAIN_OVERRIDE is set
TICKETS_DIR = "tickets"
STALE_HOURS = 2
STATUSES = ("TODO", "IN PROGRESS", "BLOCKED", "PARKED", "SPLIT", "DROPPED", "DONE")
# Board states, in the order the summary line counts them. SPLIT is only ever a container's state.
STATES = ("DONE", "MERGE PENDING", "IN PROGRESS", "BLOCKED", "PARKED", "READY", "WAITING", "DROPPED", "SPLIT")

ID = r"T\d+[a-z]?"
FILE_RE = re.compile(rf"^({ID})-[\w.-]*\.md$")
TITLE_RE = re.compile(rf"^# ({ID}) [—–-] (.+)$", re.M)
STATUS_RE = re.compile(r"^\*\*Status:\*\* (.+)$", re.M)
STATUS_VALUE_RE = re.compile(rf"^({'|'.join(STATUSES)})(?: \((.+)\))?$")
PREREQS_RE = re.compile(r"\*\*Prereqs:\*\* ([^·\n]+)")
BRANCH_RE = re.compile(r"\*\*Branch:\*\* (\S+)")
TICKET_ID_RE = re.compile(rf"^{ID}$")
CLAIM_RE = re.compile(r"^t(\d+[a-z]?)-")


@dataclass
class Ticket:
    id: str
    title: str = ""
    status: str = "TODO"
    reason: str = ""
    prereqs: list[str] = field(default_factory=list)
    branch: str = ""
    problems: list[str] = field(default_factory=list)


@dataclass
class Version:
    """One copy of a ticket file: where it was read and when it last changed (Unix seconds)."""
    source: str
    time: float
    ticket: Ticket


@dataclass
class Claim:
    branch: str
    ahead: int  # commits on the branch that main doesn't have, merges not counted
    last_commit: float | None  # time of the branch's newest commit, if it has any of its own


@dataclass
class Row:
    ticket: Ticket
    state: str  # one of STATES
    detail: str = ""
    container: bool = False  # a SPLIT ticket, shown with its pieces under it


def sort_key(tid: str) -> tuple[int, str]:
    """T07 < T07a < T08 < T100: by number, then piece letter."""
    m = re.match(r"T(\d+)([a-z]?)", tid)
    return (int(m.group(1)), m.group(2)) if m else (sys.maxsize, tid)


def parent_of(tid: str) -> str | None:
    """T07a → T07; a whole ticket has no parent."""
    return tid[:-1] if tid[-1].isalpha() else None


def parse_ticket(ticket_id: str, text: str) -> Ticket:
    t = Ticket(ticket_id)
    if m := TITLE_RE.search(text):
        t.title = m.group(2).strip()
        if m.group(1) != ticket_id:
            t.problems.append(f"title says {m.group(1)} but the file is {ticket_id}")
    else:
        t.problems.append("no '# TNN — Title' line")

    m = STATUS_RE.search(text)
    value = STATUS_VALUE_RE.match(m.group(1).strip()) if m else None
    if value:
        t.status, t.reason = value.group(1), value.group(2) or ""
    else:
        t.problems.append(f"**Status:** must be one of {', '.join(STATUSES)}, optionally followed by (reason)")

    if m := PREREQS_RE.search(text):
        raw = m.group(1).strip()
        if raw not in ("—", "-", ""):
            for token in (p.strip() for p in raw.split(",")):
                if TICKET_ID_RE.match(token):
                    t.prereqs.append(token)
                else:
                    t.problems.append(f"prereq '{token}' is not a ticket id (list whole tickets only, e.g. T01, T02)")
    else:
        t.problems.append("no **Prereqs:** field")

    if m := BRANCH_RE.search(text):
        t.branch = m.group(1)
    else:
        t.problems.append("no **Branch:** field")
    return t


def ago(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 48 * 60:
        return f"{minutes // 60} h"
    return f"{minutes // (24 * 60)} d"


def describe_claim(c: Claim, now: float) -> str:
    if c.ahead == 0 or c.last_commit is None:
        return f"branch {c.branch}, no commits yet"
    text = f"branch {c.branch}, {c.ahead} commit{'' if c.ahead == 1 else 's'} ahead, last {ago(now - c.last_commit)} ago"
    return text + (" (stale?)" if now - c.last_commit > STALE_HOURS * 3600 else "")


def prereq_problems(tid: str, t: Ticket, latest: dict[str, Ticket]) -> list[str]:
    parent = parent_of(tid)
    problems = []
    for p in t.prereqs:
        if p not in latest:
            problems.append(f"prereq {p} has no ticket file")
        elif latest[p].status == "DROPPED":
            problems.append(f"prereq {p} is dropped; depend on what replaced it, or drop this ticket too")
        if p == parent:
            problems.append(f"a piece can't wait on its own split ticket {p}")
        elif parent_of(p) and parent_of(p) != parent:
            problems.append(f"prereq {p} is a piece of {parent_of(p)}; depend on {parent_of(p)} instead")
    return problems


def build_board(
    versions: dict[str, list[Version]],
    on_main: dict[str, Ticket],
    claims: dict[str, list[Claim]],
    now: float,
) -> list[Row]:
    """One row per ticket, in id order. Pure: `collect()` does the git reading."""
    picked = {tid: max(vs, key=lambda v: (v.time, STATUSES.index(v.ticket.status))) for tid, vs in versions.items()}
    latest = {tid: v.ticket for tid, v in picked.items()}
    done_on_main = {tid for tid, t in on_main.items() if t.status == "DONE"}
    containers = {tid for tid, t in latest.items() if t.status == "SPLIT" and parent_of(tid) is None and tid not in done_on_main}
    pieces: dict[str, list[str]] = {}
    for tid in sorted(latest, key=sort_key):
        if (parent := parent_of(tid)) is not None:
            pieces.setdefault(parent, []).append(tid)

    def container_done(c: str) -> bool:
        ps = pieces.get(c, [])
        closed = [p for p in ps if p in done_on_main or latest[p].status == "DROPPED"]
        return bool(ps) and len(closed) == len(ps) and any(p in done_on_main for p in ps)

    done = done_on_main | {c for c in containers if container_done(c)}

    rows: dict[str, Row] = {}
    for tid in sorted(versions, key=sort_key):
        if tid in containers:
            continue
        t = latest[tid]
        if tid in done_on_main:
            # A newer DONE copy may have fixed its header since; anything else newer is stale, main wins.
            rows[tid] = Row(t if t.status == "DONE" else on_main[tid], "DONE")
            continue
        if t.status == "DROPPED":
            rows[tid] = Row(t, "DROPPED", t.reason)
            continue
        t.problems += prereq_problems(tid, t, latest)
        if (parent := parent_of(tid)) is not None and parent not in containers:
            where = "has no ticket file" if parent not in latest else "is not SPLIT"
            t.problems.append(f"{tid} is a piece of {parent}, but {parent} {where}")
        claimed = "; ".join(describe_claim(c, now) for c in claims.get(tid, []))
        if t.status == "DONE":
            where = ", ".join(sorted({v.source for v in versions[tid] if v.ticket.status == "DONE"}))
            rows[tid] = Row(t, "MERGE PENDING", f"done on {where}, not yet on {MAIN}")
        elif t.status in ("BLOCKED", "PARKED"):
            rows[tid] = Row(t, t.status, "; ".join(x for x in (t.reason, claimed) if x))
        elif t.status == "SPLIT":  # only a piece gets here
            t.problems.append("a piece can't be split again; add more pieces beside it instead")
            rows[tid] = Row(t, "SPLIT")
        elif t.status == "IN PROGRESS" or claimed:
            if early := [p for p in t.prereqs if p not in done]:
                t.problems.append(f"started before its prereqs are done: {', '.join(early)}")
            rows[tid] = Row(t, "IN PROGRESS", claimed or f"marked IN PROGRESS on {picked[tid].source}, but no {tid.lower()}-… branch")
        else:
            waiting = [p for p in t.prereqs if p not in done]
            if waiting:
                rows[tid] = Row(t, "WAITING", "on " + ", ".join(waiting))
            elif tid not in on_main:
                rows[tid] = Row(t, "WAITING", f"not committed on {MAIN} yet")
            else:
                rows[tid] = Row(t, "READY")

    for c in containers:
        t, ps = latest[c], pieces.get(c, [])
        if not ps:
            t.problems.append(f"SPLIT but has no pieces ({c}a, {c}b, …)")
        for claim in claims.get(c, []):
            t.problems.append(
                f"branch {claim.branch} claims {c}, which is split; rename it to the piece that holds its work"
                f" (git branch -m {claim.branch} {c.lower()}a-…)"
            )
        live = [p for p in ps if rows[p].state != "DROPPED"]
        finished = sum(rows[p].state == "DONE" for p in live)
        if container_done(c):
            state = "DONE"
        elif any(rows[p].state in ("DONE", "MERGE PENDING", "IN PROGRESS") for p in live):
            state = "IN PROGRESS"
        else:
            state = "SPLIT"
        rows[c] = Row(t, state, f"{finished} of {len(live)} pieces done", container=True)

    return [rows[tid] for tid in sorted(rows, key=sort_key)]


def next_ticket(rows: list[Row]) -> Row | None:
    return next((r for r in rows if r.state == "READY" and not r.container), None)


def render(rows: list[Row]) -> str:
    tickets = [r for r in rows if not r.container]
    counts = Counter(r.state for r in tickets)
    lines = [" · ".join([f"Tickets: {len(tickets)}", *(f"{counts[s]} {s.lower()}" for s in STATES if counts[s])])]
    for closed in ("DONE", "DROPPED"):
        ids = [r.ticket.id for r in tickets if r.state == closed]
        if ids:
            lines.append(f"{closed:<14}{' '.join(ids)}")
    open_containers = {r.ticket.id for r in rows if r.container and r.state != "DONE"}
    for r in rows:
        if r.state in ("DONE", "DROPPED"):
            continue
        indent = "  " if parent_of(r.ticket.id) in open_containers else ""
        lines.append(f"{r.state:<14}{indent}{r.ticket.id}  {r.ticket.title}" + (f" — {r.detail}" if r.detail else ""))
    nxt = next_ticket(rows)
    if nxt:
        lines.append(f"Next: {nxt.ticket.id}. Claim it: git branch {nxt.ticket.branch} {MAIN}")
    else:
        lines.append("Next: nothing is ready")
    problems = [f"  {r.ticket.id}: {p}" for r in rows for p in r.ticket.problems]
    if problems:
        lines += ["Problems:", *problems]
    return "\n".join(lines)


GRAPH_CLASSES = {  # class → (board states, Mermaid style)
    "done": (("DONE",), "fill:#dcfce7,stroke:#16a34a"),
    "doing": (("IN PROGRESS", "MERGE PENDING"), "fill:#fef9c3,stroke:#ca8a04"),
    "ready": (("READY",), "fill:#dbeafe,stroke:#2563eb"),
    "dropped": (("DROPPED",), "fill:#f3f4f6,stroke:#9ca3af,color:#6b7280,stroke-dasharray:4 3"),
}


def node(r: Row, width: int = 32) -> str:
    """T03["T03 Heuristic engine + improv…"]: the id and a short title."""
    title = r.ticket.title if len(r.ticket.title) <= width else r.ticket.title[: width - 1] + "…"
    return f'{r.ticket.id}["{r.ticket.id} {quote(title)}"]'


def quote(text: str) -> str:
    """Escape a double quote inside a Mermaid label."""
    return text.replace('"', "#quot;")


def graph(rows: list[Row]) -> str:
    """The prereq graph as a Mermaid flowchart; a split ticket is a subgraph around its pieces."""
    by_id = {r.ticket.id: r for r in rows}
    containers = [r.ticket.id for r in rows if r.container]
    lines = ["flowchart LR"]
    for c in containers:
        lines.append(f'  subgraph {c} ["{c} {quote(by_id[c].ticket.title)}"]')
        lines += [f"    {node(by_id[p])}" for p in by_id if parent_of(p) == c]
        lines.append("  end")
    edges = []
    for tid, r in by_id.items():
        parent = parent_of(tid)
        for p in r.ticket.prereqs:
            # A piece's outside prereq usually repeats its container's; draw it once, on the container.
            if parent in by_id and parent_of(p) != parent and p in by_id[parent].ticket.prereqs:
                continue
            edges.append(f"  {p} --> {tid}")
    lines += [f"  {node(r)}" for tid, r in by_id.items() if tid not in containers and parent_of(tid) not in containers]
    lines += edges
    for cls, (states, style) in GRAPH_CLASSES.items():
        ids = [tid for tid, r in by_id.items() if r.state in states and not r.container]
        if ids:
            lines += [f"  classDef {cls} {style}", f"  class {','.join(ids)} {cls}"]
    container_styles = {"DONE": "fill:#f0fdf4,stroke:#16a34a", "IN PROGRESS": "fill:#fefce8,stroke:#ca8a04"}
    lines += [f"  style {c} {container_styles[by_id[c].state]}" for c in containers if by_id[c].state in container_styles]
    return "\n".join(lines)


# --- Reading git -------------------------------------------------------------------------------------------------


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def try_git(repo: Path, *args: str) -> str | None:
    """Like git(), but None when the command fails (an unset config key, a missing ref)."""
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else None


def default_branch(repo: Path) -> str:
    """MAIN_OVERRIDE, else origin's HEAD, else init.defaultBranch, else main or master: the first that exists."""
    if MAIN_OVERRIDE:
        return MAIN_OVERRIDE
    origin = try_git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    candidates = [origin.removeprefix("origin/") if origin else None, try_git(repo, "config", "init.defaultBranch"), "main", "master"]
    for b in candidates:
        if b and try_git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{b}") is not None:
            return b
    return "main"


def ticket_id(name: str) -> str | None:
    m = FILE_RE.match(name)
    return m.group(1) if m else None


def change_times(repo: Path, ref: str) -> dict[str, float]:
    """Ticket file name → time of the newest commit on `ref` that touched it."""
    out = git(repo, "log", "--format=\x01%ct", "--name-only", ref, "--", f"{TICKETS_DIR}/")
    times: dict[str, float] = {}
    current = 0.0
    for line in out.splitlines():
        if line.startswith("\x01"):
            current = float(line[1:])
        elif line.strip():
            times.setdefault(Path(line).name, current)
    return times


def committed_files(repo: Path, ref: str) -> dict[str, str]:
    """Ticket file name → content, as committed on `ref`."""
    listing = try_git(repo, "ls-tree", "--name-only", f"{ref}:{TICKETS_DIR}")  # None: no tickets/ on this ref
    names = [n for n in (listing or "").split() if ticket_id(n)]
    if not names:
        return {}
    batch = "".join(f"{ref}:{TICKETS_DIR}/{n}\n" for n in names).encode()
    out = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch"], input=batch, capture_output=True, check=True).stdout
    files, pos = {}, 0
    for name in names:
        end = out.index(b"\n", pos)
        header = out[pos:end].split()
        if len(header) < 3 or header[1] == b"missing":
            pos = end + 1
            continue
        size = int(header[2])
        files[name] = out[end + 1 : end + 1 + size].decode()
        pos = end + 1 + size + 1
    return files


def worktrees(repo: Path) -> list[tuple[Path, str | None]]:
    """(path, branch or None if detached) for every worktree that still exists."""
    out, result = git(repo, "worktree", "list", "--porcelain"), []
    for block in out.strip().split("\n\n"):
        fields = dict(line.split(" ", 1) if " " in line else (line, "") for line in block.splitlines())
        path = Path(fields.get("worktree", ""))
        if "bare" in fields or not path.is_dir():
            continue
        branch = fields.get("branch", "").removeprefix("refs/heads/") or None
        result.append((path, branch))
    return result


def collect(repo: Path) -> tuple[dict[str, list[Version]], dict[str, Ticket], dict[str, list[Claim]]]:
    versions: dict[str, list[Version]] = {}

    def add(source: str, files: dict[str, str], times: dict[str, float]) -> dict[str, Ticket]:
        parsed = {}
        for name, text in files.items():
            tid = ticket_id(name)
            if tid:
                parsed[tid] = parse_ticket(tid, text)
                versions.setdefault(tid, []).append(Version(source, times.get(name, 0.0), parsed[tid]))
        return parsed

    on_main = add(MAIN, committed_files(repo, MAIN), change_times(repo, MAIN))

    checked_out = set()
    for path, branch in worktrees(repo):
        checked_out.add(branch)
        times = change_times(path, "HEAD")
        dirty = {Path(line[3:]).name for line in git(path, "status", "--porcelain", "--", f"{TICKETS_DIR}/").splitlines()}
        files = {}
        for f in (path / TICKETS_DIR).glob("T*.md"):
            files[f.name] = f.read_text()
            if f.name in dirty:
                times[f.name] = f.stat().st_mtime
        add(f"{branch or path.name} (worktree)", files, times)

    branches = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").split()
    for b in branches:
        if b != MAIN and b not in checked_out:
            add(b, committed_files(repo, b), change_times(repo, b))

    claims: dict[str, list[Claim]] = {}
    for b in branches:
        m = CLAIM_RE.match(b)
        tid = f"T{m.group(1)}" if m else None
        if not tid or (tid in on_main and on_main[tid].status == "DONE"):
            continue
        ahead = int(git(repo, "rev-list", "--count", "--no-merges", f"{MAIN}..{b}").strip())
        last = float(git(repo, "log", "-1", "--format=%ct", b).strip()) if ahead else None
        claims.setdefault(tid, []).append(Claim(b, ahead, last))
    return versions, on_main, claims


def main(argv: list[str]) -> int:
    global MAIN
    repo = Path(__file__).resolve().parent.parent
    MAIN = default_branch(repo)
    rows = build_board(*collect(repo), now=time.time())
    if "--next" in argv:
        nxt = next_ticket(rows)
        if not nxt:
            return 1
        print(nxt.ticket.id, nxt.ticket.branch)
        return 0
    print(graph(rows) if "--graph" in argv else render(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
