"""Generator at demo scale: speed budgets for 10k Customers and calibration on a 2,000-Customer run."""

import time
from datetime import timedelta

import pytest

from offer_engine.db import connect
from offer_engine.sim.generate import run
from offer_engine.sim.generate.history import simulate_day

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def big_world(tmp_path_factory):
    conn = connect(tmp_path_factory.mktemp("big") / "big.db")
    started = time.perf_counter()
    ctx = run(conn, n_customers=10_000, months=12, seed=7)
    yield ctx, time.perf_counter() - started
    conn.close()


def test_10k_customers_12_months_generate_under_5_minutes(big_world):
    _, seconds = big_world
    assert seconds < 300


def test_simulate_day_for_10k_customers_under_5_seconds(big_world):
    """The live world's first week after the clock start, from the generated state (T17's use)."""
    ctx, _ = big_world
    rng = ctx.rng("live")
    for offset in range(7):
        started = time.perf_counter()
        events = simulate_day(ctx, ctx.end + timedelta(days=offset), rng)
        assert time.perf_counter() - started < 5
        assert events


@pytest.fixture(scope="module")
def world_2k(tmp_path_factory):
    conn = connect(tmp_path_factory.mktemp("2k") / "2k.db")
    run(conn, n_customers=2_000, months=12, seed=7)
    yield conn
    conn.close()


def test_cart_abandonment_within_target_2(world_2k):
    abandoned, carts = world_2k.execute(
        "SELECT SUM(kind = 'cart_abandoned'), SUM(kind = 'add_to_cart') FROM events"
    ).fetchone()
    assert 0.70 <= abandoned / carts <= 0.80


def test_orders_per_active_customer_within_target_5a(world_2k):
    per_buyer = world_2k.execute(
        "SELECT AVG(n) FROM (SELECT COUNT(*) AS n FROM events WHERE kind = 'order' GROUP BY customer_id)"
    ).fetchone()[0]
    assert 4 <= per_buyer <= 9


def test_top_20pct_spend_share_within_target_8(world_2k):
    spend = sorted(
        (
            row[0]
            for row in world_2k.execute(
                "SELECT SUM(amount) FROM events WHERE kind = 'order' GROUP BY customer_id"
            )
        ),
        reverse=True,
    )
    top = spend[: len(spend) // 5]
    assert 0.65 <= sum(top) / sum(spend) <= 0.75
