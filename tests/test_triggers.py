"""Event Triggers (T19, PLAN §3.1): the pure detectors, then `on_hour` and de-duplication on a generated world."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from offer_engine import clock, pipeline, triggers
from offer_engine.domain import Event, TriggerKind
from offer_engine.triggers import Hit

NOW = clock.START + timedelta(hours=10)
CART = TriggerKind.CART_ABANDONED
POINTS = TriggerKind.POINTS_EXPIRING
GAP = TriggerKind.LONG_GAP
FIRST = TriggerKind.FIRST_ORDER_DELIVERED


def at(minutes_ago: int) -> datetime:
    return NOW - timedelta(minutes=minutes_ago)


# --- Detectors ---------------------------------------------------------------------------------


def test_cart_abandoned_hits_each_new_cart_abandoned_event():
    events = [
        Event("A", at(50), "add_to_cart"),
        Event("A", at(40), "cart_abandoned"),
        Event("B", at(30), "cart_abandoned"),
        Event("B", at(5), "cart_abandoned"),
        Event("C", at(20), "order"),
    ]
    assert triggers.cart_abandoned(events) == [
        Hit("A", CART, at(40).isoformat()),
        Hit("B", CART, at(30).isoformat()),
        Hit("B", CART, at(5).isoformat()),
    ]


def test_first_order_delivered_only_for_the_earliest_delivery():
    events = [
        Event("A", at(30), "delivered"),
        Event("B", at(20), "delivered"),
        Event("C", at(10), "delivered"),
        Event("C", at(10), "delivered"),
        Event("D", at(5), "order"),
    ]
    first = {"A": at(30), "B": at(60 * 24 * 30), "C": at(10), "D": at(5)}
    assert triggers.first_order_delivered(events, first) == [
        Hit("A", FIRST, "first"),
        Hit("C", FIRST, "first"),
    ]


def test_points_expiring_within_the_warning_window_keyed_by_expiry_date():
    balances = [
        ("in", 120, NOW + timedelta(days=3)),
        ("edge", 10, NOW + timedelta(days=7)),
        ("later", 120, NOW + timedelta(days=7, minutes=1)),
        ("empty", 0, NOW + timedelta(days=2)),
        ("gone", 50, NOW),
        ("never", 50, None),
    ]
    hits = triggers.points_expiring(balances, NOW, warning_days=7)
    assert hits == [
        Hit("in", POINTS, (NOW + timedelta(days=3)).date().isoformat()),
        Hit("edge", POINTS, (NOW + timedelta(days=7)).date().isoformat()),
    ]


def test_long_gap_only_in_the_hour_the_gap_is_reached():
    gap = timedelta(days=45)
    last_orders = [
        ("crossed", NOW - gap - timedelta(minutes=30)),
        ("exactly", NOW - gap),
        ("last_hour", NOW - gap - timedelta(hours=1)),
        ("not_yet", NOW - gap + timedelta(minutes=1)),
        ("long_ago", NOW - gap - timedelta(days=10)),
    ]
    hits = triggers.long_gap(last_orders, NOW, gap_days=45)
    assert hits == [
        Hit("crossed", GAP, (NOW - gap - timedelta(minutes=30)).isoformat()),
        Hit("exactly", GAP, (NOW - gap).isoformat()),
    ]


# --- on_hour on a generated world --------------------------------------------------------------


@pytest.fixture
def decided(monkeypatch):
    """Replace the pipeline with a recorder: each call is (Customer ID, Trigger, now)."""
    calls: list[tuple[str, TriggerKind, datetime]] = []

    def decide(conn, customer_id, trigger, now):
        calls.append((customer_id, trigger, now))
        return SimpleNamespace(id=len(calls))

    monkeypatch.setattr(pipeline, "decide", decide)
    return calls


def report():
    return SimpleNamespace(counts=Counter())


def customers(conn, n):
    return [row[0] for row in conn.execute("SELECT id FROM customers ORDER BY id LIMIT ?", (n,))]


def add_event(conn, customer_id, when, kind):
    conn.execute(
        "INSERT INTO events (customer_id, at, kind, amount) VALUES (?, ?, ?, 500)",
        (customer_id, when.isoformat(timespec="seconds"), kind),
    )
    return Event(customer_id, when, kind, amount=500.0)


@pytest.fixture
def scene(world):
    """A world with nobody near a Trigger, then one Customer at each: a cart abandoned and a first order delivered
    this hour, points expiring in 3 days, and a last order 45 days ago (the default `long_gap_days`)."""
    world.execute("UPDATE customers SET points_balance = 0")
    world.execute("DELETE FROM events WHERE kind IN ('order', 'delivered')")
    cart, first, points, gap = customers(world, 4)
    new = [add_event(world, cart, at(40), "cart_abandoned"), add_event(world, first, at(20), "delivered")]
    world.execute(
        "UPDATE customers SET points_balance = 300, points_expire_at = ? WHERE id = ?",
        ((NOW + timedelta(days=3)).isoformat(), points),
    )
    add_event(world, gap, NOW - timedelta(days=45, minutes=30), "order")
    world.commit()
    return SimpleNamespace(conn=world, new=new, cart=cart, first=first, points=points, gap=gap)


def test_on_hour_asks_the_pipeline_once_per_hit_and_counts_decisions(scene, decided):
    rep = report()
    triggers.on_hour(scene.conn, NOW, scene.new, rep)
    assert sorted(decided) == sorted(
        [
            (scene.cart, CART, NOW),
            (scene.first, FIRST, NOW),
            (scene.points, POINTS, NOW),
            (scene.gap, GAP, NOW),
        ]
    )
    assert rep.counts == Counter(
        {
            "decisions.cart_abandoned": 1,
            "decisions.first_order_delivered": 1,
            "decisions.points_expiring": 1,
            "decisions.long_gap": 1,
        }
    )
    logged = scene.conn.execute("SELECT customer_id, kind, key, at FROM trigger_log ORDER BY kind").fetchall()
    assert len(logged) == 4 and all(row["at"] == NOW.isoformat() for row in logged)


def test_each_underlying_event_fires_once(scene, decided):
    triggers.on_hour(scene.conn, NOW, scene.new, report())
    # The same events seen again, and the next day's hours with the points still expiring and the gap still open.
    rep = report()
    triggers.on_hour(scene.conn, NOW, scene.new, rep)
    for hours in range(1, 25):
        triggers.on_hour(scene.conn, NOW + timedelta(hours=hours), [], rep)
    assert len(decided) == 4 and not rep.counts


def test_a_new_expiry_date_or_a_new_last_order_fires_again(scene, decided):
    triggers.on_hour(scene.conn, NOW, scene.new, report())
    later = NOW + timedelta(days=50)
    scene.conn.execute(
        "UPDATE customers SET points_expire_at = ? WHERE id = ?",
        ((later + timedelta(days=2)).isoformat(), scene.points),
    )
    add_event(scene.conn, scene.gap, later - timedelta(days=45, minutes=10), "order")
    scene.conn.commit()
    decided.clear()
    triggers.on_hour(scene.conn, later, [], report())
    assert sorted(decided) == sorted([(scene.points, POINTS, later), (scene.gap, GAP, later)])


def test_a_later_delivery_is_not_a_first_order(scene, decided):
    triggers.on_hour(scene.conn, NOW, scene.new, report())
    decided.clear()
    second = add_event(scene.conn, scene.first, NOW + timedelta(days=4, minutes=-10), "delivered")
    triggers.on_hour(scene.conn, NOW + timedelta(days=4), [second], report())
    assert (scene.first, FIRST, NOW + timedelta(days=4)) not in decided


def test_a_gap_only_counts_from_the_latest_order(scene, decided):
    add_event(scene.conn, scene.gap, NOW - timedelta(days=3), "order")
    triggers.on_hour(scene.conn, NOW, [], report())
    assert scene.gap not in {c[0] for c in decided}


def test_a_failed_decision_leaves_the_event_free_to_fire(scene, monkeypatch):
    real = pipeline.decide

    def broken(*args):
        raise RuntimeError("down")

    monkeypatch.setattr(pipeline, "decide", broken)
    hit = Hit(scene.cart, CART, at(40).isoformat())
    with pytest.raises(RuntimeError):
        triggers.fire(scene.conn, hit, NOW)
    assert scene.conn.execute("SELECT COUNT(*) FROM trigger_log").fetchone()[0] == 0
    monkeypatch.setattr(pipeline, "decide", real)
    assert triggers.fire(scene.conn, hit, NOW) is not None
    assert triggers.fire(scene.conn, hit, NOW) is None


def test_on_hour_runs_the_real_pipeline(scene):
    rep = report()
    triggers.on_hour(scene.conn, NOW, scene.new, rep)
    rows = scene.conn.execute("SELECT customer_id, trigger FROM decisions ORDER BY id").fetchall()
    assert sorted(map(tuple, rows)) == sorted(
        [(scene.cart, CART), (scene.first, FIRST), (scene.points, POINTS), (scene.gap, GAP)]
    )
    assert sum(rep.counts.values()) == 4
