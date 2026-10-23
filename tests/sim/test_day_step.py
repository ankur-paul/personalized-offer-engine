"""The live world's day-step (T17) on a generated 200-Customer world."""

import shutil
import time
from datetime import datetime, timedelta

import pytest

from offer_engine import clock, daily_sweep, triggers
from offer_engine.db import connect
from offer_engine.sim.generate import run
from offer_engine.sim.world import day_step, outcomes

START = clock.START
DAY_END = START + timedelta(days=1)


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    path = tmp_path_factory.mktemp("live") / "world.db"
    conn = connect(path)
    run(conn, 200, months=3, seed=11)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    return path


@pytest.fixture
def make_world(template, tmp_path):
    """Private copies of the generated world, as open connections."""
    opened = []

    def make(name="world"):
        path = tmp_path / f"{name}.db"
        shutil.copy(template, path)
        conn = connect(path)
        opened.append(conn)
        return conn

    yield make
    for conn in opened:
        conn.close()


@pytest.fixture
def world(make_world):
    return make_world()


def events(conn, since=START):
    return conn.execute(
        "SELECT customer_id, at, kind, category, product_id, amount FROM events WHERE at >= ? ORDER BY id",
        (since.isoformat(),),
    ).fetchall()


def as_tuples(rows):
    return [tuple(row) for row in rows]


def add_offer(conn, customer_id, status="queued", send_at=START + timedelta(hours=10), code=None):
    conn.execute(
        "INSERT INTO offers (code, customer_id, offer_type, created_at, send_at, expires_at, rule_version, "
        "worst_case_cost, expected_cost, status, source) VALUES (?, ?, 'nudge', ?, ?, ?, 0, 0, 0, ?, 'test')",
        (
            code or f"POE-{customer_id}",
            customer_id,
            START.isoformat(),
            send_at.isoformat(),
            (send_at + timedelta(days=3)).isoformat(),
            status,
        ),
    )
    conn.commit()


def make_shopper(conn, customer_id):
    """Visits often and carts almost every session, so a normal day has orders."""
    conn.execute(
        "UPDATE sim_customer_traits SET visit_rate = 40, buy_propensity = 30, churned_at = NULL "
        "WHERE customer_id = ?",
        (customer_id,),
    )
    conn.commit()


def customer_ids(conn, n):
    return [row[0] for row in conn.execute("SELECT id FROM customers ORDER BY id LIMIT ?", (n,))]


def test_advancing_24_hours_moves_the_clock_and_fills_only_that_window(world):
    before = world.execute("SELECT MAX(at) FROM events").fetchone()[0]
    assert before < START.isoformat()
    report = day_step.advance(world, 24)
    assert clock.now(world) == DAY_END
    assert (report.start, report.end) == (START, DAY_END)
    new = events(world)
    assert new and all(START.isoformat() <= row["at"] < DAY_END.isoformat() for row in new)
    assert report.counts["session"] == sum(row["kind"] == "session" for row in new) > 0
    assert sum(report.counts[k] for k in report.counts if k != "offers_sent") == len(new)


def test_queued_offers_to_non_chat_customers_are_sent_at_send_at(world):
    plain, chatty, later = customer_ids(world, 3)
    world.execute("INSERT INTO chats (customer_id, chat_id, kind) VALUES (?, 1, 'bot')", (chatty,))
    add_offer(world, plain)
    add_offer(world, chatty)
    add_offer(world, later, send_at=START + timedelta(days=2))
    report = day_step.advance(world, 9)
    assert {r[0] for r in world.execute("SELECT status FROM offers")} == {"queued"}
    report = day_step.advance(world, 1)
    statuses = dict(world.execute("SELECT customer_id, status FROM offers").fetchall())
    assert statuses == {plain: "sent", chatty: "queued", later: "queued"}
    assert report.counts["offers_sent"] == 1


def test_a_customer_with_an_active_offer_gets_no_organic_order(world):
    holder, control = customer_ids(world, 2)
    make_shopper(world, holder)
    make_shopper(world, control)
    add_offer(world, holder, status="sent", send_at=START - timedelta(hours=1))
    day_step.advance(world, 24)
    kinds = {
        cid: [row["kind"] for row in events(world) if row["customer_id"] == cid] for cid in (holder, control)
    }
    assert "add_to_cart" in kinds[holder] and "order" not in kinds[holder]
    assert "order" in kinds[control]


def test_an_expired_offer_no_longer_blocks_orders(world):
    (holder,) = customer_ids(world, 1)
    make_shopper(world, holder)
    add_offer(world, holder, status="sent", send_at=START - timedelta(days=4))
    day_step.advance(world, 24)
    assert "order" in [row["kind"] for row in events(world) if row["customer_id"] == holder]


def test_hooks_run_every_hour_in_order_with_that_hours_events(world, monkeypatch):
    calls = []
    monkeypatch.setattr(outcomes, "on_hour", lambda conn, now, report, rng: calls.append(("outcomes", now)))
    monkeypatch.setattr(
        triggers,
        "on_hour",
        lambda conn, now, new_events, report: calls.append(("triggers", now, new_events)),
    )
    monkeypatch.setattr(daily_sweep, "on_hour", lambda conn, now, report: calls.append(("daily_sweep", now)))
    day_step.advance(world, 24)

    assert len(calls) == 72
    hours = [START + timedelta(hours=h) for h in range(1, 25)]
    assert [c[0] for c in calls] == ["outcomes", "triggers", "daily_sweep"] * 24
    assert [c[1] for c in calls] == [h for h in hours for _ in range(3)]
    trigger_calls = [c for c in calls if c[0] == "triggers"]
    for now, (_, _, new_events) in zip(hours, trigger_calls):
        assert all(now - timedelta(hours=1) <= e.at < now for e in new_events)
    assert sum(len(c[2]) for c in trigger_calls) == len(events(world))


def test_hooks_get_the_hours_end_and_the_clock_agrees(world, monkeypatch):
    seen = []
    monkeypatch.setattr(daily_sweep, "on_hour", lambda conn, now, report: seen.append((now, clock.now(conn))))
    day_step.advance(world, 2)
    assert seen == [(START + timedelta(hours=h),) * 2 for h in (1, 2)]


def test_same_state_and_seed_give_the_same_events(make_world):
    first, second = make_world("a"), make_world("b")
    day_step.advance(first, 48, rng_seed=3)
    day_step.advance(second, 48, rng_seed=3)
    assert as_tuples(events(first)) == as_tuples(events(second))
    third = make_world("c")
    day_step.advance(third, 48, rng_seed=4)
    assert as_tuples(events(third)) != as_tuples(events(first))


def test_stopping_mid_day_changes_nothing(make_world):
    whole, split = make_world("whole"), make_world("split")
    day_step.advance(whole, 48)
    for hours in (5, 19, 13, 11):
        day_step.advance(split, hours)
    assert as_tuples(events(split)) == as_tuples(events(whole))
    points = "SELECT id, points_balance, points_expire_at FROM customers ORDER BY id"
    assert as_tuples(split.execute(points)) == as_tuples(whole.execute(points))


def test_an_offer_changes_only_its_customers_events(make_world):
    """T26 relies on this: Policies compared from the same state differ only where Offers changed behaviour."""
    plain, offered = make_world("plain"), make_world("offered")
    holder = customer_ids(offered, 1)[0]
    for conn in (plain, offered):
        make_shopper(conn, holder)
    add_offer(offered, holder, status="sent", send_at=START - timedelta(hours=1))
    day_step.advance(plain, 24)
    day_step.advance(offered, 24)
    others = [as_tuples(r for r in events(conn) if r["customer_id"] != holder) for conn in (plain, offered)]
    assert others[0] == others[1]
    mine = [as_tuples(r for r in events(conn) if r["customer_id"] == holder) for conn in (plain, offered)]
    assert mine[0] != mine[1]


def test_history_orders_are_delivered_in_the_live_world(world):
    recent = world.execute(
        "SELECT customer_id, at, amount FROM events WHERE kind = 'order' AND at >= ?",
        ((START - timedelta(days=3)).isoformat(),),
    ).fetchall()
    assert recent
    day_step.advance(world, 72)
    delivered = {
        (row["customer_id"], row["at"], row["amount"]) for row in events(world) if row["kind"] == "delivered"
    }
    for order in recent:
        due = datetime.fromisoformat(order["at"]) + timedelta(days=3)
        assert (order["customer_id"], due.isoformat(), order["amount"]) in delivered


def test_points_expire_at_their_time_and_customers_table_follows(world):
    (customer,) = customer_ids(world, 1)
    world.execute("UPDATE sim_customer_traits SET visit_rate = 0 WHERE customer_id = ?", (customer,))
    world.execute(
        "UPDATE customers SET points_balance = 420, points_expire_at = ? WHERE id = ?",
        ((START + timedelta(hours=5)).isoformat(), customer),
    )
    world.execute("DELETE FROM sim_pending_events WHERE customer_id = ?", (customer,))
    world.commit()
    day_step.advance(world, 24)
    mine = [
        (row["kind"], row["at"], row["amount"]) for row in events(world) if row["customer_id"] == customer
    ]
    assert mine == [("points_expired", (START + timedelta(hours=5)).isoformat(), 420.0)]
    row = world.execute(
        "SELECT points_balance, points_expire_at FROM customers WHERE id = ?", (customer,)
    ).fetchone()
    assert tuple(row) == (0, None)


def test_earned_points_reach_the_customers_table(world):
    day_step.advance(world, 72)
    earned = world.execute(
        "SELECT customer_id, MAX(at) AS at FROM events WHERE kind = 'points_earned' AND at >= ? GROUP BY customer_id",
        (START.isoformat(),),
    ).fetchall()
    assert earned
    for row in earned:
        expires = world.execute("SELECT points_expire_at FROM customers WHERE id = ?", (row["customer_id"],))
        assert expires.fetchone()[0] == (datetime.fromisoformat(row["at"]) + timedelta(days=180)).isoformat()


def test_tester_copies_do_nothing_organic(world):
    (source,) = customer_ids(world, 1)
    copy_id = f"{source}-t42"
    world.execute(
        "INSERT INTO customers (id, signup_at, city_tier, device, channel, loyalty_tier, is_tester_copy, "
        "source_customer_id) SELECT ?, signup_at, city_tier, device, channel, loyalty_tier, 1, id "
        "FROM customers WHERE id = ?",
        (copy_id, source),
    )
    world.commit()
    day_step.advance(world, 24)
    assert not [row for row in events(world) if row["customer_id"] == copy_id]


def test_an_empty_database_just_moves_the_clock(conn):
    report = day_step.advance(conn, 30)
    assert clock.now(conn) == START + timedelta(hours=30)
    assert not +report.counts


def test_rejects_moving_backwards(world):
    with pytest.raises(ValueError):
        day_step.advance(world, -1)


@pytest.mark.slow
def test_one_day_for_10k_customers_under_15_seconds(tmp_path):
    conn = connect(tmp_path / "big.db")
    run(conn, 10_000, months=2, seed=7)
    started = time.perf_counter()
    report = day_step.advance(conn, 24)
    elapsed = time.perf_counter() - started
    conn.close()
    assert report.counts["session"] > 1000
    assert elapsed < 15
