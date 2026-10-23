"""Versioned Rule settings. Version 0 is the RuleSet defaults; every save or revert adds a new version."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from offer_engine import clock
from offer_engine.domain import RuleSet


@dataclass(frozen=True)
class RuleVersion:
    version: int
    rules: RuleSet
    author: str
    note: str
    created_at: datetime  # simulated time
    saved_at: datetime  # wall-clock time, UTC


def current_rules(conn: sqlite3.Connection) -> tuple[int, RuleSet]:
    row = conn.execute("SELECT version, rules FROM rule_versions ORDER BY version DESC LIMIT 1").fetchone()
    if row is None:
        return 0, RuleSet()
    return row["version"], RuleSet.from_dict(json.loads(row["rules"]))


def rules_at_version(conn: sqlite3.Connection, version: int) -> RuleSet:
    if version == 0:
        return RuleSet()
    row = conn.execute("SELECT rules FROM rule_versions WHERE version = ?", (version,)).fetchone()
    if row is None:
        raise ValueError(f"no rule version {version}")
    return RuleSet.from_dict(json.loads(row["rules"]))


def save_rules(conn: sqlite3.Connection, rules: RuleSet, author: str, note: str = "") -> int:
    version = current_rules(conn)[0] + 1
    conn.execute(
        "INSERT INTO rule_versions (version, rules, author, note, created_at, saved_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            version,
            json.dumps(rules.to_dict(), sort_keys=True),
            author,
            note,
            clock.now(conn).isoformat(timespec="seconds"),
            datetime.now(UTC).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return version


def list_versions(conn: sqlite3.Connection) -> list[RuleVersion]:
    """Saved versions, newest first. Version 0 (defaults) is implicit and not listed."""
    return [
        RuleVersion(
            version=row["version"],
            rules=RuleSet.from_dict(json.loads(row["rules"])),
            author=row["author"],
            note=row["note"],
            created_at=datetime.fromisoformat(row["created_at"]),
            saved_at=datetime.fromisoformat(row["saved_at"]),
        )
        for row in conn.execute("SELECT * FROM rule_versions ORDER BY version DESC")
    ]


def revert(conn: sqlite3.Connection, version: int, author: str) -> int:
    """Save a new version equal to `version`. History is never rewritten."""
    return save_rules(conn, rules_at_version(conn, version), author, note=f"revert to v{version}")
