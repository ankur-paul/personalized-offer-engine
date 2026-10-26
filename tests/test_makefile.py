import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="needs make")


def dry_run(target: str, db: Path) -> list[str]:
    """The commands `make -n TARGET` would run against the database at `db`."""
    result = subprocess.run(
        ["make", "-n", "-C", str(ROOT), target, f"DB={db}"], capture_output=True, text=True, check=True
    )
    return [line for line in result.stdout.splitlines() if not line.startswith("make")]


def test_first_run_builds_the_world_then_starts(tmp_path):
    commands = dry_run("run", tmp_path / "missing.db")
    expected = [
        "uv sync",
        "check-env",
        "generate --customers 10000 --seed 7",
        "lift fit",
        "chats link-showcase",
        "offer-engine start",
    ]
    positions = [next(i for i, c in enumerate(commands) if step in c) for step in expected]
    assert positions == sorted(positions)


def test_an_existing_world_is_kept(tmp_path):
    db = tmp_path / "offer_engine.db"
    db.touch()
    commands = dry_run("run", db)
    assert not any("generate" in c or "link-showcase" in c for c in commands)
    assert commands[-1] == "uv run offer-engine start"


def test_help_lists_the_demo_targets():
    result = subprocess.run(["make", "-C", str(ROOT), "help"], capture_output=True, text=True, check=True)
    targets = [line.split()[0] for line in result.stdout.splitlines() if line.startswith("  ")]
    assert {"demo-reset", "demo-snapshot"} <= set(targets)


@pytest.mark.parametrize("target", ["demo-reset", "demo-snapshot"])
def test_demo_targets_run_the_demo_command(tmp_path, target):
    assert dry_run(target, tmp_path / "x.db") == [f"uv run offer-engine demo {target.removeprefix('demo-')}"]
