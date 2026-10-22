import os
import subprocess
import time
from pathlib import Path

import board
from board import Claim, Ticket, Version, build_board, next_ticket, parse_ticket, render

NOW = 1_800_000_000.0


def ticket_text(tid: str, status: str = "TODO", prereqs: str = "—", branch: str | None = None, title: str = "Thing") -> str:
    return (
        f"# {tid} — {title}\n**Status:** {status}\n"
        f"**Lane:** A · **Prereqs:** {prereqs} · **Branch:** {branch or tid.lower() + '-x'}\n\n## Goal\n"
    )


def v(tid: str, source: str = "main", at: float = 0.0, **kw) -> Version:
    return Version(source, at, parse_ticket(tid, ticket_text(tid, **kw)))


def board_of(*versions: Version, claims: dict | None = None):
    by_id: dict[str, list[Version]] = {}
    for x in versions:
        by_id.setdefault(x.ticket.id, []).append(x)
    on_main = {x.ticket.id: x.ticket for x in versions if x.source == "main"}
    return {r.ticket.id: r for r in build_board(by_id, on_main, claims or {}, NOW)}


# --- parse_ticket ---


def test_parses_a_full_header():
    t = parse_ticket("T05", ticket_text("T05", status="IN PROGRESS", prereqs="T01, T02", branch="t05-shell", title="Shell"))
    assert (t.title, t.status, t.reason, t.prereqs, t.branch, t.problems) == (
        "Shell", "IN PROGRESS", "", ["T01", "T02"], "t05-shell", []
    )


def test_status_reason_in_brackets():
    t = parse_ticket("T12", ticket_text("T12", status="BLOCKED (needs human: user test)"))
    assert (t.status, t.reason) == ("BLOCKED", "needs human: user test")


def test_unknown_status_is_a_problem():
    t = parse_ticket("T01", ticket_text("T01", status="WIP"))
    assert t.status == "TODO" and "Status" in t.problems[0]


def test_dash_means_no_prereqs():
    assert parse_ticket("T00", ticket_text("T00", prereqs="—")).prereqs == []


def test_prereq_that_is_not_a_whole_ticket_is_a_problem():
    t = parse_ticket("T07", ticket_text("T07", prereqs="T02, T05 (T04 optional)"))
    assert t.prereqs == ["T02"]
    assert "'T05 (T04 optional)'" in t.problems[0]


def test_title_id_must_match_file():
    t = parse_ticket("T03", ticket_text("T04"))
    assert "title says T04" in t.problems[0]


def test_missing_fields_are_problems():
    t = parse_ticket("T01", "just text")
    assert len(t.problems) == 4  # title, status, prereqs, branch


# --- build_board ---


def test_done_on_main_is_final_even_if_a_newer_copy_says_otherwise():
    rows = board_of(v("T01", status="DONE", at=1), v("T01", source="old-branch", at=5, status="TODO"))
    assert rows["T01"].state == "DONE"


def test_done_uses_a_newer_done_copy_for_its_header():
    rows = board_of(v("T01", status="DONE", at=1, title="Old"), v("T01", source="wt", at=5, status="DONE", title="New"))
    assert rows["T01"].ticket.title == "New"


def test_done_only_on_a_branch_is_merge_pending():
    rows = board_of(v("T01", at=1), v("T01", source="t01-x", at=5, status="DONE"))
    assert rows["T01"].state == "MERGE PENDING"
    assert "t01-x" in rows["T01"].detail


def test_newest_copy_wins():
    rows = board_of(v("T12", at=1, status="IN PROGRESS"), v("T12", source="wt", at=9, status="BLOCKED (needs human)"))
    assert (rows["T12"].state, rows["T12"].detail) == ("BLOCKED", "needs human")


def test_ready_when_every_prereq_is_done_on_main():
    rows = board_of(v("T01", status="DONE"), v("T02", prereqs="T01"))
    assert rows["T02"].state == "READY"


def test_waiting_lists_unfinished_prereqs():
    rows = board_of(v("T01"), v("T02", status="DONE"), v("T03", prereqs="T01, T02"))
    assert (rows["T03"].state, rows["T03"].detail) == ("WAITING", "on T01")


def test_prereq_done_only_on_a_branch_still_waits():
    rows = board_of(v("T01", at=1), v("T01", source="t01-x", at=2, status="DONE"), v("T02", prereqs="T01"))
    assert rows["T02"].state == "WAITING"


def test_a_claim_branch_makes_a_todo_ticket_in_progress():
    rows = board_of(v("T02"), claims={"T02": [Claim("t02-x", 3, NOW - 600)]})
    assert rows["T02"].state == "IN PROGRESS"
    assert rows["T02"].detail == "branch t02-x, 3 commits ahead, last 10 min ago"


def test_fresh_and_stale_claims():
    fresh = board_of(v("T02"), claims={"T02": [Claim("t02-x", 0, None)]})
    stale = board_of(v("T02"), claims={"T02": [Claim("t02-x", 1, NOW - 3 * 3600)]})
    assert fresh["T02"].detail == "branch t02-x, no commits yet"
    assert stale["T02"].detail == "branch t02-x, 1 commit ahead, last 3 h ago (stale?)"


def test_in_progress_without_a_branch_says_so():
    rows = board_of(v("T02", status="IN PROGRESS"))
    assert "no t02-… branch" in rows["T02"].detail


def test_blocked_keeps_its_reason_and_shows_the_branch():
    rows = board_of(v("T12", status="BLOCKED (user test)"), claims={"T12": [Claim("t12-design", 0, None)]})
    assert (rows["T12"].state, rows["T12"].detail) == ("BLOCKED", "user test; branch t12-design, no commits yet")


def test_unknown_prereq_is_a_problem():
    rows = board_of(v("T02", prereqs="T09"))
    assert rows["T02"].state == "WAITING"
    assert "prereq T09 has no ticket file" in rows["T02"].ticket.problems


# --- next / render ---


def test_next_is_the_lowest_ready_ticket():
    rows = board_of(v("T01", status="DONE"), v("T03", prereqs="T01"), v("T02", prereqs="T01"), v("T04", status="PARKED"))
    assert next_ticket(list(rows.values())).ticket.id == "T02"


def test_render_summary_next_and_problems():
    rows = list(board_of(v("T01", status="DONE"), v("T02", prereqs="T01"), v("T03", prereqs="T02, oops")).values())
    out = render(rows)
    assert out.splitlines()[0] == "Tickets: 3 · 1 done · 1 ready · 1 waiting"
    assert "DONE          T01" in out
    assert "Next: T02. Claim it: git branch t02-x main" in out
    assert "T03: prereq 'oops' is not a ticket id" in out


def test_render_with_nothing_ready():
    assert "Next: nothing is ready" in render(list(board_of(v("T01", status="PARKED")).values()))


# --- collect: a real repo with a branch and a worktree ---


def sh(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout


def write(root: Path, name: str, text: str) -> None:
    (root / "tickets").mkdir(exist_ok=True)
    (root / "tickets" / name).write_text(text)


def test_collect_reads_main_branches_and_worktrees(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    sh(repo, "init", "-q", "-b", "main")
    write(repo, "T01-a.md", ticket_text("T01", status="DONE"))
    write(repo, "T02-b.md", ticket_text("T02", prereqs="T01", branch="t02-b"))
    write(repo, "T03-c.md", ticket_text("T03", prereqs="T02"))
    write(repo, "T04-d.md", ticket_text("T04", prereqs="T01", branch="t04-d"))
    write(repo, "README.md", "not a ticket")
    sh(repo, "add", ".")
    sh(repo, "commit", "-qm", "tickets")

    # T02: claimed by a branch with one commit of its own, not checked out anywhere.
    sh(repo, "branch", "t02-b")
    sh(repo, "switch", "-q", "t02-b")
    write(repo, "T02-b.md", ticket_text("T02", status="IN PROGRESS", prereqs="T01", branch="t02-b"))
    sh(repo, "commit", "-qam", "claim")
    sh(repo, "switch", "-q", "main")

    # T03: someone marks it BLOCKED in another worktree without committing; a new T05 exists only there.
    wt = tmp_path / "wt"
    sh(repo, "worktree", "add", "-q", "-b", "side", str(wt))
    time.sleep(1.1)  # dirty files are dated by mtime, commits by whole seconds
    write(wt, "T03-c.md", ticket_text("T03", status="BLOCKED (waiting on a person)", prereqs="T02"))
    write(wt, "T05-e.md", ticket_text("T05", prereqs="T04"))

    rows = {r.ticket.id: r for r in build_board(*board.collect(repo), now=time.time())}
    assert {tid: r.state for tid, r in rows.items()} == {
        "T01": "DONE", "T02": "IN PROGRESS", "T03": "BLOCKED", "T04": "READY", "T05": "WAITING",
    }
    assert rows["T02"].detail.startswith("branch t02-b, 1 commit ahead")
    assert rows["T03"].detail == "waiting on a person"


# --- ids, dashes, statuses ---


def test_any_dash_in_the_title():
    for dash in ("—", "–", "-"):
        assert parse_ticket("T03", f"# T03 {dash} Thing\n**Status:** TODO\n**Prereqs:** — · **Branch:** t03-x").title == "Thing"


def test_piece_and_long_ids_parse():
    t = parse_ticket("T07a", ticket_text("T07a", prereqs="T07b, T100", branch="t07a-x"))
    assert (t.prereqs, t.problems) == (["T07b", "T100"], [])


def test_file_names_tell_pieces_from_slugs():
    assert [board.ticket_id(n) for n in ("T07a-x.md", "T07-api.md", "T100-x.md", "README.md")] == ["T07a", "T07", "T100", None]


def test_claim_branches_tell_pieces_from_slugs():
    assert [board.CLAIM_RE.match(b).group(1) for b in ("t07a-x", "t07-a-star", "t100-x")] == ["07a", "07", "100"]


def test_ids_sort_by_number_then_piece():
    assert sorted(["T100", "T08", "T07a", "T07", "T11"], key=board.sort_key) == ["T07", "T07a", "T08", "T11", "T100"]


def test_split_and_dropped_parse():
    assert parse_ticket("T07", ticket_text("T07", status="SPLIT")).status == "SPLIT"
    t = parse_ticket("T09", ticket_text("T09", status="DROPPED (replaced by T24)"))
    assert (t.status, t.reason) == ("DROPPED", "replaced by T24")


# --- splits and drops ---


def test_a_split_ticket_counts_its_pieces():
    rows = board_of(
        v("T07", status="SPLIT"), v("T07a", status="DONE"), v("T07b", prereqs="T07a"), v("T08", prereqs="T07"),
    )
    assert (rows["T07"].state, rows["T07"].detail, rows["T07"].container) == ("IN PROGRESS", "1 of 2 pieces done", True)
    assert rows["T07b"].state == "READY"
    assert (rows["T08"].state, rows["T08"].detail) == ("WAITING", "on T07")


def test_a_split_ticket_is_done_when_every_piece_is_done_or_dropped():
    rows = board_of(
        v("T07", status="SPLIT"), v("T07a", status="DONE"), v("T07b", status="DROPPED (not needed)"), v("T08", prereqs="T07"),
    )
    assert rows["T07"].state == "DONE"
    assert rows["T08"].state == "READY"


def test_only_dropped_pieces_is_not_done():
    rows = board_of(v("T07", status="SPLIT"), v("T07a", status="DROPPED (x)"), v("T08", prereqs="T07"))
    assert rows["T07"].state == "SPLIT"
    assert rows["T08"].state == "WAITING"


def test_a_split_with_nothing_started_is_never_ready_or_next():
    rows = board_of(v("T07", status="SPLIT"), v("T07a"), v("T07b", prereqs="T07a"))
    assert (rows["T07"].state, rows["T07"].detail) == ("SPLIT", "0 of 2 pieces done")
    assert next_ticket(list(rows.values())).ticket.id == "T07a"


def test_a_piece_done_only_on_a_branch_keeps_its_split_in_progress():
    rows = board_of(v("T07", status="SPLIT"), v("T07a", at=1), v("T07a", source="t07a-x", at=2, status="DONE"))
    assert (rows["T07a"].state, rows["T07"].state) == ("MERGE PENDING", "IN PROGRESS")


def test_depending_on_a_piece_from_outside_is_a_problem():
    rows = board_of(v("T07", status="SPLIT"), v("T07a"), v("T08", prereqs="T07a"))
    assert "prereq T07a is a piece of T07; depend on T07 instead" in rows["T08"].ticket.problems


def test_pieces_may_wait_on_siblings_but_not_on_their_split_ticket():
    rows = board_of(v("T07", status="SPLIT"), v("T07a"), v("T07b", prereqs="T07a, T07"))
    assert rows["T07b"].ticket.problems == ["a piece can't wait on its own split ticket T07"]


def test_a_piece_needs_a_split_parent():
    rows = board_of(v("T07"), v("T07a"), v("T09a"))
    assert "T07a is a piece of T07, but T07 is not SPLIT" in rows["T07a"].ticket.problems
    assert "T09a is a piece of T09, but T09 has no ticket file" in rows["T09a"].ticket.problems


def test_a_piece_cant_be_split_again():
    rows = board_of(v("T07", status="SPLIT"), v("T07a", status="SPLIT"))
    assert "a piece can't be split again; add more pieces beside it instead" in rows["T07a"].ticket.problems


def test_a_split_without_pieces_is_a_problem():
    rows = board_of(v("T07", status="SPLIT"))
    assert rows["T07"].ticket.problems == ["SPLIT but has no pieces (T07a, T07b, …)"]


def test_a_branch_left_on_a_split_ticket_is_a_problem():
    rows = board_of(v("T07", status="SPLIT"), v("T07a"), claims={"T07": [Claim("t07-x", 2, NOW)]})
    assert "rename it to the piece that holds its work (git branch -m t07-x t07a-…)" in rows["T07"].ticket.problems[0]


def test_dropped_is_closed_but_never_counts_as_done():
    rows = board_of(v("T05", status="DROPPED (replaced by T09)"), v("T06", prereqs="T05"))
    assert (rows["T05"].state, rows["T05"].detail) == ("DROPPED", "replaced by T09")
    assert rows["T06"].state == "WAITING"
    assert "prereq T05 is dropped; depend on what replaced it, or drop this ticket too" in rows["T06"].ticket.problems


def test_render_counts_pieces_and_indents_them_under_their_split():
    rows = list(board_of(
        v("T06", status="DONE"), v("T07", status="SPLIT", title="Big"), v("T07a", status="DONE"),
        v("T07b", prereqs="T07a", title="Rest"), v("T08", status="DROPPED (no)"),
    ).values())
    out = render(rows)
    assert out.splitlines()[0] == "Tickets: 4 · 2 done · 1 ready · 1 dropped"
    assert "DONE          T06 T07a" in out
    assert "DROPPED       T08" in out
    assert "IN PROGRESS   T07  Big — 1 of 2 pieces done" in out
    assert "READY           T07b  Rest" in out


def test_graph_draws_splits_edges_and_states():
    rows = list(board_of(
        v("T01", status="DONE"), v("T02"), v("T07", status="SPLIT", prereqs="T01"),
        v("T07a", prereqs="T01"), v("T07b", prereqs="T07a"), v("T09", status="DROPPED (x)"),
    ).values())
    out = board.graph(rows).splitlines()
    assert out[0] == "flowchart LR"
    assert out[1:5] == ['  subgraph T07 ["T07 Thing"]', '    T07a["T07a Thing"]', '    T07b["T07b Thing"]', "  end"]
    assert "  T01 --> T07" in out and "  T07a --> T07b" in out
    assert "  T01 --> T07a" not in out  # repeats the container's edge
    assert '  T02["T02 Thing"]' in out and '  T09["T09 Thing"]' in out  # every node is declared, linked or not
    assert "  class T01 done" in out and "  class T09 dropped" in out and "  class T02,T07a ready" in out
    assert not any(line.startswith("  classDef doing") for line in out)  # only the classes in use


# --- default branch ---


def test_default_branch_falls_back_to_master(tmp_path, monkeypatch):
    sh(tmp_path, "init", "-q", "-b", "master")
    sh(tmp_path, "commit", "-q", "--allow-empty", "-m", "x")
    monkeypatch.setattr(board, "MAIN_OVERRIDE", None)
    assert board.default_branch(tmp_path) == "master"
    monkeypatch.setattr(board, "MAIN_OVERRIDE", "trunk")
    assert board.default_branch(tmp_path) == "trunk"


def test_collect_on_master_claims_a_piece(tmp_path, monkeypatch):
    sh(tmp_path, "init", "-q", "-b", "master")
    write(tmp_path, "T07-big.md", ticket_text("T07", status="SPLIT"))
    write(tmp_path, "T07a-x.md", ticket_text("T07a", branch="t07a-x"))
    write(tmp_path, "T07b-y.md", ticket_text("T07b", prereqs="T07a", branch="t07b-y"))
    sh(tmp_path, "add", ".")
    sh(tmp_path, "commit", "-qm", "split")
    sh(tmp_path, "branch", "t07a-x")
    monkeypatch.setattr(board, "MAIN", board.default_branch(tmp_path))
    rows = {r.ticket.id: r for r in build_board(*board.collect(tmp_path), now=time.time())}
    assert {tid: r.state for tid, r in rows.items()} == {"T07": "IN PROGRESS", "T07a": "IN PROGRESS", "T07b": "WAITING"}


# --- found in the first dry run ---


def test_starting_before_prereqs_are_done_is_a_problem():
    rows = board_of(v("T01"), v("T02", prereqs="T01"), claims={"T02": [Claim("t02-x", 1, NOW)]})
    assert rows["T02"].state == "IN PROGRESS"
    assert "started before its prereqs are done: T01" in rows["T02"].ticket.problems


def test_an_empty_board_has_no_trailing_separator():
    assert render([]).splitlines()[0] == "Tickets: 0"


def test_graph_styles_a_split_in_progress():
    rows = list(board_of(v("T07", status="SPLIT"), v("T07a", status="DONE"), v("T07b")).values())
    assert "  style T07 fill:#fefce8,stroke:#ca8a04" in board.graph(rows)


def test_collect_skips_branches_without_tickets_and_merges_dont_count(tmp_path):
    sh(tmp_path, "init", "-q", "-b", "main")
    sh(tmp_path, "commit", "-q", "--allow-empty", "-m", "before tickets")
    sh(tmp_path, "branch", "old-feature")  # made before tickets/ existed
    write(tmp_path, "T01-a.md", ticket_text("T01", branch="t01-a"))
    sh(tmp_path, "add", ".")
    sh(tmp_path, "commit", "-qm", "tickets")
    sh(tmp_path, "switch", "-q", "-c", "t01-a")
    sh(tmp_path, "commit", "-q", "--allow-empty", "-m", "work")
    sh(tmp_path, "switch", "-q", "main")
    sh(tmp_path, "commit", "-q", "--allow-empty", "-m", "elsewhere")
    sh(tmp_path, "switch", "-q", "t01-a")
    sh(tmp_path, "merge", "-q", "--no-edit", "main")
    sh(tmp_path, "switch", "-q", "main")
    rows = {r.ticket.id: r for r in build_board(*board.collect(tmp_path), now=time.time())}
    assert rows["T01"].detail.startswith("branch t01-a, 1 commit ahead")


def test_a_header_without_a_lane_parses():
    t = parse_ticket("T03", "# T03 — Thing\n**Status:** TODO\n**Prereqs:** T01, T02 · **Branch:** t03-thing\n")
    assert (t.prereqs, t.branch, t.problems) == (["T01", "T02"], "t03-thing", [])


def test_the_readme_template_parses():
    import pytest

    readme = Path(__file__).parent / "templates" / "README.md"  # only in the skill's own folder, not in a repo
    if not readme.exists():
        pytest.skip("no README template next to this file")
    template = readme.read_text().split("```md\n")[1].split("```")[0]
    t = parse_ticket("T05", template.replace("TNN", "T05").replace("tNN", "t05"))
    assert t.problems == []


def test_graph_shortens_titles_and_escapes_quotes():
    rows = list(board_of(v("T01", title='Say "hi" to everyone in the whole wide world today')).values())
    assert '  T01["T01 Say #quot;hi#quot; to everyone in the who…"]' in board.graph(rows)


def test_a_ticket_not_on_the_default_branch_is_not_ready():
    rows = board_of(v("T01", source="main (worktree)"))
    assert (rows["T01"].state, rows["T01"].detail) == ("WAITING", "not committed on main yet")
    assert next_ticket(list(rows.values())) is None
