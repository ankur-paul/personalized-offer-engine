"""Preview impact of a Rule change (T28; PLAN §6, QnA Q13): one Daily Sweep at the next 10:00, run with the current
Rules and again with the edited ones, each on its own copy of the database, and the difference.

The rules chooser decides for everyone, so a preview makes no agent calls. The live database is only read. The two
sweeps run in two child processes (`python -m offer_engine.sim.preview`), as one takes about 45 s on 10k Customers.
Not `multiprocessing`: its children first rerun the parent's `__main__`, which inside Streamlit is a console page.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from offer_engine import clock, daily_sweep, pipeline, rules_store
from offer_engine.choosers import rules_chooser
from offer_engine.db import connect, migrate
from offer_engine.domain import RuleSet, TriggerKind
from offer_engine.sim.offline import copy_db

PREVIEW_AUTHOR = "preview"


@dataclass(frozen=True)
class SweepSummary:
    """What one Daily Sweep decided."""

    offers: int
    worst_case_cost: float
    expected_cost: float
    by_type: Counter[str]  # Offer Type → Offers
    binding: Counter[str]  # Binding Rule → Decisions, Offer or No Offer
    offered: frozenset[str]  # Customers who got an Offer

    def to_json(self) -> str:
        return json.dumps(
            {
                "offers": self.offers,
                "worst_case_cost": self.worst_case_cost,
                "expected_cost": self.expected_cost,
                "by_type": self.by_type,
                "binding": self.binding,
                "offered": sorted(self.offered),
            }
        )

    @classmethod
    def from_json(cls, text: str) -> SweepSummary:
        data = json.loads(text)
        return cls(
            data["offers"],
            data["worst_case_cost"],
            data["expected_cost"],
            Counter(data["by_type"]),
            Counter(data["binding"]),
            frozenset(data["offered"]),
        )


@dataclass(frozen=True)
class Change:
    name: str
    current: int
    new: int

    @property
    def change(self) -> int:
        return self.new - self.current


@dataclass(frozen=True)
class PreviewResult:
    at: datetime  # the simulated time of the previewed sweep
    current: SweepSummary
    new: SweepSummary
    runtime_seconds: float = 0.0

    @property
    def offers_delta(self) -> int:
        return self.new.offers - self.current.offers

    @property
    def worst_case_delta(self) -> float:
        return self.new.worst_case_cost - self.current.worst_case_cost

    @property
    def expected_delta(self) -> float:
        return self.new.expected_cost - self.current.expected_cost

    @property
    def newly_blocked(self) -> frozenset[str]:
        """Customers who get an Offer under the current Rules and none under the new ones."""
        return self.current.offered - self.new.offered

    @property
    def newly_unblocked(self) -> frozenset[str]:
        return self.new.offered - self.current.offered

    def type_changes(self) -> list[Change]:
        return _changes(self.current.by_type, self.new.by_type)

    def binding_changes(self) -> list[Change]:
        """Binding Rules whose count changed, biggest change first."""
        return _changes(self.current.binding, self.new.binding)

    def headline(self) -> str:
        """`+1,240 Offers · +₹38,200 worst-case cost · +₹6,100 expected cost`"""
        return (
            f"{self.offers_delta:+,} Offers · {_rupees(self.worst_case_delta)} worst-case cost · "
            f"{_rupees(self.expected_delta)} expected cost"
        )


def preview(conn, new_rules: RuleSet, *, parallel: bool = True) -> PreviewResult:
    """Diff one Daily Sweep at the next 10:00 under the current Rules and under `new_rules`. `conn` must be a file
    database; it is only read, through copies next to it. `parallel=False` runs both sweeps in this process."""
    started = time.monotonic()
    src = Path(conn.execute("PRAGMA database_list").fetchone()["file"])
    if not src.name:
        raise ValueError("preview needs a database file, not an in-memory one")
    at = next_sweep(clock.now(conn))
    with tempfile.TemporaryDirectory(prefix=".preview-", dir=src.parent) as tmp:
        jobs = [(src, Path(tmp) / "current.db", at, None), (src, Path(tmp) / "new.db", at, new_rules)]
        if parallel:
            children = [_start_child(*job) for job in jobs]
            try:
                current, new = (
                    _finish_child(child, job[1]) for child, job in zip(children, jobs, strict=True)
                )
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                        child.wait()
        else:
            current, new = (_sweep_copy(*job) for job in jobs)
    return PreviewResult(at, current, new, time.monotonic() - started)


def next_sweep(now: datetime) -> datetime:
    """The first 10:00 after `now`. At 10:00 itself, today's sweep has already run."""
    at = now.replace(hour=daily_sweep.SWEEP_HOUR, minute=0, second=0, microsecond=0)
    return at if at > now else at + timedelta(days=1)


def _start_child(src: Path, path: Path, at: datetime, rules: RuleSet | None) -> subprocess.Popen:
    args = [sys.executable, "-m", __name__, str(src), str(path), at.isoformat()]
    if rules is not None:
        args.append(json.dumps(rules.to_dict()))
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)


def _finish_child(child: subprocess.Popen, path: Path) -> SweepSummary:
    _, stderr = child.communicate()
    if child.returncode != 0:
        raise RuntimeError(f"the preview sweep on {path.name} failed:\n{stderr}")
    return SweepSummary.from_json(path.with_suffix(".json").read_text())


def _sweep_copy(src: Path, path: Path, at: datetime, rules: RuleSet | None = None) -> SweepSummary:
    """Run the Daily Sweep at `at` on a copy of `src`, under `rules` if given, else the copy's current Rules."""
    copy_db(src, path)
    conn = connect(path)
    try:
        # The copy is thrown away, so commits skip the disk sync, as in the offline Policy runs.
        conn.execute("PRAGMA synchronous = OFF")
        migrate(conn)
        if rules is not None:
            rules_store.save_rules(conn, rules, PREVIEW_AUTHOR)
        with pipeline.chooser_override(lambda state, trigger: rules_chooser.choose, trace=False):
            daily_sweep.sweep(conn, at)
        return _summarise(conn, at)
    finally:
        conn.close()


def _summarise(conn, at: datetime) -> SweepSummary:
    rows = conn.execute(
        "SELECT d.customer_id, d.binding_rule, o.offer_type, o.worst_case_cost, o.expected_cost FROM decisions d "
        "LEFT JOIN offers o ON o.id = d.offer_id WHERE d.at = ? AND d.trigger = ?",
        (at.isoformat(timespec="seconds"), TriggerKind.DAILY_SWEEP),
    ).fetchall()
    offers = [row for row in rows if row["offer_type"] is not None]
    return SweepSummary(
        offers=len(offers),
        worst_case_cost=sum(row["worst_case_cost"] for row in offers),
        expected_cost=sum(row["expected_cost"] for row in offers),
        by_type=Counter(row["offer_type"] for row in offers),
        binding=Counter(row["binding_rule"] for row in rows if row["binding_rule"]),
        offered=frozenset(row["customer_id"] for row in offers),
    )


def _changes(current: Counter[str], new: Counter[str]) -> list[Change]:
    changes = [Change(name, current[name], new[name]) for name in current.keys() | new.keys()]
    changes = [c for c in changes if c.change]
    return sorted(changes, key=lambda c: (-abs(c.change), c.name))


def _rupees(amount: float) -> str:
    sign = "-" if round(amount) < 0 else "+"
    return f"{sign}₹{abs(amount):,.0f}"


def main(argv: list[str]) -> None:
    """`python -m offer_engine.sim.preview SRC COPY AT [RULES_JSON]`: one sweep, its summary to COPY's `.json`."""
    src, path, at = Path(argv[0]), Path(argv[1]), datetime.fromisoformat(argv[2])
    rules = RuleSet.from_dict(json.loads(argv[3])) if len(argv) > 3 else None
    path.with_suffix(".json").write_text(_sweep_copy(src, path, at, rules).to_json())


if __name__ == "__main__":
    main(sys.argv[1:])
