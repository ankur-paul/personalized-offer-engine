"""Demo snapshot and reset with SQLite's backup API (T36, QnA Q46)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from offer_engine import clock, pipeline
from offer_engine.cli import main
from offer_engine.db import connect
from offer_engine.demo.snapshot import reset, snapshot
from offer_engine.domain import TriggerKind
from offer_engine.sim.world import day_step


def contents(conn) -> dict[str, list[tuple]]:
    """Every row of every table."""
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    return {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY rowid")] for t in tables}


def change(conn) -> None:
    """A Decision and a day of the live world."""
    customer_id = conn.execute("SELECT id FROM customers ORDER BY id LIMIT 1").fetchone()[0]
    pipeline.decide(conn, customer_id, TriggerKind.CART_ABANDONED, clock.now(conn) + timedelta(hours=1))
    day_step.advance(conn, 24, 7)


def test_reset_brings_back_the_snapshot(world, tmp_path):
    path = tmp_path / "demo.db"
    before = contents(world)
    snapshot(world, path)
    change(world)
    assert contents(world) != before
    reset(world, path)
    assert contents(world) == before


def test_another_open_connection_sees_the_reset(world, tmp_path):
    path = tmp_path / "demo.db"
    snapshot(world, path)
    before_time = clock.now(world)
    other = connect(world.execute("PRAGMA database_list").fetchone()["file"])
    change(world)
    assert clock.now(other) > before_time
    reset(world, path)
    assert clock.now(other) == before_time
    assert other.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 0
    other.execute("UPDATE clock SET now = now")
    other.commit()
    other.close()
    assert world.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_the_snapshot_is_one_file(world, tmp_path):
    path = tmp_path / "demo.db"
    snapshot(world, path)
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("demo")) == ["demo.db"]
    snapshot(world, path)  # replaces the earlier one


def test_reset_without_a_snapshot_says_what_to_run(world, tmp_path):
    with pytest.raises(FileNotFoundError, match="offer-engine demo snapshot"):
        reset(world, tmp_path / "missing.db")


def test_the_commands_print_the_time_and_customer_count(world, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DB_PATH", world.execute("PRAGMA database_list").fetchone()["file"])
    path = str(tmp_path / "demo.db")
    assert main(["demo", "snapshot", "--path", path]) == 0
    change(world)
    assert main(["demo", "reset", "--path", path]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"Saved the world to {path}: 2026-12-01 00:00, 50 Customers"
    assert out[1] == f"Reset the world from {path}: 2026-12-01 00:00, 50 Customers"


def test_reset_command_without_a_snapshot_exits(world, tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", world.execute("PRAGMA database_list").fetchone()["file"])
    with pytest.raises(SystemExit, match="demo snapshot"):
        main(["demo", "reset", "--path", str(tmp_path / "missing.db")])
