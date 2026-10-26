"""Copy the database to a snapshot file and back with SQLite's backup API (T36).

`reset` writes into the open database instead of replacing the file, so the bots and the console keep their
connections and see the snapshot's data on their next query.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_PATH = Path("data/demo.db")


def snapshot(conn: sqlite3.Connection, path: Path = DEFAULT_PATH) -> None:
    """Copy the database behind `conn` to `path`, replacing any earlier snapshot only once the copy is whole."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.unlink(missing_ok=True)
    dest = sqlite3.connect(partial)
    try:
        conn.commit()
        conn.backup(dest)
        # One self-contained file, with no -wal or -shm beside it.
        dest.execute("PRAGMA journal_mode = DELETE")
    finally:
        dest.close()
    partial.replace(path)


def reset(conn: sqlite3.Connection, path: Path = DEFAULT_PATH) -> None:
    """Overwrite the database behind `conn` with the snapshot at `path`."""
    if not path.is_file():
        raise FileNotFoundError(f"no snapshot at {path}; run `offer-engine demo snapshot` first")
    source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        conn.commit()
        source.backup(conn)
    finally:
        source.close()
