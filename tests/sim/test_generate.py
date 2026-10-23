import hashlib
from collections import Counter
from datetime import date, datetime, timedelta

import pytest

from offer_engine import clock
from offer_engine.cli import main
from offer_engine.db import connect, load_catalog
from offer_engine.sim.generate import history_start, run
from offer_engine.sim.generate.history import EVENT_KINDS

TABLES = (
    "categories",
    "products",
    "customers",
    "sim_customer_traits",
    "events",
    "sim_ground_truth",
    "sim_response_class",
)
MARGIN_TARGETS = {
    "grocery": (12, 18),
    "electronics": (8, 15),
    "fashion": (40, 50),
    "beauty": (35, 45),
    "home": (25, 35),
}


def table_hashes(conn):
    hashes = {}
    for table in TABLES:
        digest = hashlib.sha256()
        for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1"):
            digest.update(repr(tuple(row)).encode())
        hashes[table] = digest.hexdigest()
    return hashes


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    conn = connect(tmp_path_factory.mktemp("world") / "world.db")
    run(conn, n_customers=150, months=12, seed=7)
    yield conn
    conn.close()


def events(conn, kind):
    return [
        (row["customer_id"], datetime.fromisoformat(row["at"]), row["product_id"], row["amount"])
        for row in conn.execute("SELECT * FROM events WHERE kind = ? ORDER BY id", (kind,))
    ]


def test_same_seed_gives_identical_database(world, tmp_path):
    again = connect(tmp_path / "again.db")
    run(again, n_customers=150, months=12, seed=7)
    assert table_hashes(again) == table_hashes(world)


def test_other_seed_differs(world, tmp_path):
    other = connect(tmp_path / "other.db")
    run(other, n_customers=150, months=12, seed=8)
    assert table_hashes(other)["events"] != table_hashes(world)["events"]


def test_rerun_wipes_and_refills(tmp_path):
    conn = connect(tmp_path / "rerun.db")
    run(conn, n_customers=20, months=2, seed=3)
    first = table_hashes(conn)
    clock.advance(conn, 24)
    run(conn, n_customers=20, months=2, seed=3)
    assert table_hashes(conn) == first
    assert clock.now(conn) == clock.START


def test_catalog_and_customers(world):
    catalog = load_catalog(world)
    assert set(catalog.categories) == set(MARGIN_TARGETS)
    per_category = Counter(p.category for p in catalog.products.values())
    assert all(count >= 35 for count in per_category.values())
    ids = [row[0] for row in world.execute("SELECT id FROM customers ORDER BY id")]
    assert ids == [f"C{n:05d}" for n in range(1, 151)]
    traits = world.execute("SELECT COUNT(*) FROM sim_customer_traits").fetchone()[0]
    assert traits == 150
    tiers = {row[0] for row in world.execute("SELECT DISTINCT loyalty_tier FROM customers")}
    assert tiers <= {"bronze", "silver", "gold", "platinum"}
    assert world.execute("SELECT MIN(points_balance) FROM customers").fetchone()[0] >= 0


def test_margins_within_benchmark_target_7(world):
    for category in load_catalog(world).categories.values():
        lo, hi = MARGIN_TARGETS[category.name]
        assert lo <= category.margin_pct <= hi


def test_every_event_belongs_to_a_customer_and_a_listed_kind(world):
    orphans = world.execute(
        "SELECT COUNT(*) FROM events e LEFT JOIN customers c ON c.id = e.customer_id WHERE c.id IS NULL"
    ).fetchone()[0]
    assert orphans == 0
    kinds = {row[0] for row in world.execute("SELECT DISTINCT kind FROM events")}
    assert kinds == set(EVENT_KINDS)


def test_events_fall_between_signup_and_clock_start(world):
    start = datetime.combine(history_start(clock.START.date(), 12), datetime.min.time())
    bad = world.execute(
        "SELECT COUNT(*) FROM events e JOIN customers c ON c.id = e.customer_id"
        " WHERE e.at < c.signup_at OR e.at < ? OR e.at >= ?",
        (start.isoformat(), clock.START.isoformat()),
    ).fetchone()[0]
    assert bad == 0


def test_delivered_follows_order_by_three_days(world):
    orders = Counter((cid, at, product, amount) for cid, at, product, amount in events(world, "order"))
    delivered = events(world, "delivered")
    assert delivered
    for cid, at, product, amount in delivered:
        assert orders[(cid, at - timedelta(days=3), product, amount)] > 0
    cutoff = clock.START - timedelta(days=3)
    due = sum(n for (_, at, _, _), n in orders.items() if at < cutoff)
    assert len(delivered) == due


def test_festive_weeks_have_more_orders_than_the_yearly_weekly_mean(world):
    order_days = [at.date() for _, at, _, _ in events(world, "order")]
    yearly_weekly_mean = len(order_days) / 52
    festive = [d for d in order_days if date(2026, 9, 15) <= d <= date(2026, 11, 7)]
    festive_weekly_mean = len(festive) / (54 / 7)
    peak_week = [d for d in order_days if date(2026, 11, 1) <= d <= date(2026, 11, 7)]
    assert festive_weekly_mean > yearly_weekly_mean
    assert len(peak_week) > 2 * yearly_weekly_mean


def test_cart_funnel(world):
    carts = len(events(world, "add_to_cart"))
    abandoned = len(events(world, "cart_abandoned"))
    assert 0.6 < abandoned / carts < 0.85


def test_history_start_counts_back_whole_months():
    assert history_start(date(2026, 12, 1), 12) == date(2025, 12, 1)
    assert history_start(date(2026, 12, 1), 6) == date(2026, 6, 1)
    assert history_start(date(2026, 3, 1), 3) == date(2025, 12, 1)


def test_generate_command_prints_counts(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "cli.db"))
    assert main(["generate", "--customers", "15", "--months", "1", "--seed", "7"]) == 0
    out = capsys.readouterr().out
    assert "customers" in out and "events by kind" in out and "session" in out
    assert main(["generate", "--customers", "15", "--months", "1", "--seed", "7"]) == 0
    assert capsys.readouterr().out == out
