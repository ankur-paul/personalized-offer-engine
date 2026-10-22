"""SQLite connection, schema migrations and the catalog loader."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from offer_engine.domain import Catalog, Category, Product

SCHEMA_DIR = Path(__file__).parent / "schema"


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open the database (default: `DB_PATH` from settings) with WAL, foreign keys and `sqlite3.Row` rows."""
    if path is None:
        from offer_engine.config import load_settings

        path = load_settings().db_path
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(conn: sqlite3.Connection, schema_dir: Path = SCHEMA_DIR) -> list[str]:
    """Apply each `*.sql` file in `schema_dir` not applied yet, in name order. Returns the files applied now."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (filename TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    conn.commit()
    applied = {row[0] for row in conn.execute("SELECT filename FROM schema_migrations")}
    newly_applied = []
    for sql_file in sorted(schema_dir.glob("*.sql")):
        if sql_file.name in applied:
            continue
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        # One script so the file and its record commit together, or not at all.
        try:
            conn.executescript(
                f"BEGIN;\n{sql_file.read_text()}\n"
                f"INSERT INTO schema_migrations (filename, applied_at) VALUES ('{sql_file.name}', '{stamp}');\n"
                "COMMIT;"
            )
        except sqlite3.Error:
            if conn.in_transaction:
                conn.rollback()
            raise
        newly_applied.append(sql_file.name)
    return newly_applied


def load_catalog(conn: sqlite3.Connection) -> Catalog:
    categories = {
        row["name"]: Category(row["name"], row["margin_pct"], row["avg_basket"])
        for row in conn.execute("SELECT name, margin_pct, avg_basket FROM categories")
    }
    products = {
        row["id"]: Product(row["id"], row["name"], row["category"], row["price"])
        for row in conn.execute("SELECT id, name, category, price FROM products")
    }
    return Catalog(categories, products)
