import shutil
import sqlite3

import pytest

from offer_engine.db import SCHEMA_DIR, connect, load_catalog, migrate
from offer_engine.domain import Catalog, Category, Product

CORE_TABLES = {
    "categories",
    "products",
    "customers",
    "events",
    "chats",
    "offers",
    "decisions",
    "rule_versions",
    "clock",
}


def tables(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_connect_settings(tmp_path):
    conn = connect(tmp_path / "sub" / "x.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert (tmp_path / "sub" / "x.db").exists()


def test_connect_defaults_to_settings_db_path(clean_env, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(clean_env / "from_env.db"))
    connect().close()
    assert (clean_env / "from_env.db").exists()


def test_migrate_creates_core_tables_and_is_idempotent(tmp_path):
    conn = connect(tmp_path / "x.db")
    assert migrate(conn) == ["t02_core.sql"]
    assert CORE_TABLES <= tables(conn)
    assert migrate(conn) == []
    assert [row[0] for row in conn.execute("SELECT filename FROM schema_migrations")] == ["t02_core.sql"]


def test_later_schema_file_applies_after_core(tmp_path):
    schema = tmp_path / "schema"
    schema.mkdir()
    shutil.copy(SCHEMA_DIR / "t02_core.sql", schema)
    # References a core table, so it only works if t02_core.sql ran first.
    (schema / "t05_extra.sql").write_text(
        "CREATE TABLE extra (customer_id TEXT REFERENCES customers(id));\n"
        "CREATE INDEX extra_customer ON extra(customer_id);\n"
    )
    conn = connect(tmp_path / "x.db")
    assert migrate(conn, schema) == ["t02_core.sql", "t05_extra.sql"]
    assert "extra" in tables(conn)

    (schema / "t09_more.sql").write_text("CREATE TABLE more (id INTEGER);")
    assert migrate(conn, schema) == ["t09_more.sql"]


def test_failed_schema_file_is_not_recorded(tmp_path):
    schema = tmp_path / "schema"
    schema.mkdir()
    (schema / "t01_ok.sql").write_text("CREATE TABLE ok (id INTEGER);")
    (schema / "t02_bad.sql").write_text("CREATE TABLE half (id INTEGER);\nTHIS IS NOT SQL;")
    conn = connect(tmp_path / "x.db")
    with pytest.raises(sqlite3.Error):
        migrate(conn, schema)
    recorded = [row[0] for row in conn.execute("SELECT filename FROM schema_migrations")]
    assert recorded == ["t01_ok.sql"]
    assert "half" not in tables(conn)


def test_load_catalog(conn):
    conn.execute("INSERT INTO categories VALUES ('fashion', 45.0, 1200.0)")
    conn.execute("INSERT INTO products VALUES ('P001', 'Kurta', 'fashion', 899.0)")
    assert load_catalog(conn) == Catalog(
        categories={"fashion": Category("fashion", 45.0, 1200.0)},
        products={"P001": Product("P001", "Kurta", "fashion", 899.0)},
    )


def test_foreign_keys_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO products VALUES ('P001', 'Kurta', 'no_such_category', 899.0)")
