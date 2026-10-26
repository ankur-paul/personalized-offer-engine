"""Daily Sweep (T20, PLAN §3.1): runs at 10:00 simulated, chat-attached Customers first, skips anyone decided in
the last 24 simulated hours."""

from __future__ import annotations

import time
from collections import Counter
from datetime import timedelta
from types import SimpleNamespace

import pytest

from offer_engine import clock, daily_sweep, pipeline
from offer_engine.budget import week_start
from offer_engine.choosers import rules_chooser
from offer_engine.customers import load_customer_states
from offer_engine.db import connect, load_catalog
from offer_engine.domain import BudgetState, OfferType, Proposal, RuleSet, TriggerKind
from offer_engine.rules import eligible_set
from offer_engine.rules_store import save_rules

NOW = clock.START + timedelta(hours=10)
SWEEP = TriggerKind.DAILY_SWEEP


def report():
    return SimpleNamespace(counts=Counter())


def ids(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT id FROM customers ORDER BY id")]


def attach(conn, customer_ids):
    conn.executemany(
        "INSERT INTO chats VALUES (?, ?, 'tester')", [(cid, 1000 + i) for i, cid in enumerate(customer_ids)]
    )
    conn.commit()


def sweep_decisions(conn):
    return conn.execute("SELECT * FROM decisions WHERE trigger = ? ORDER BY id", (SWEEP,)).fetchall()


def add_decision(conn, customer_id, at):
    conn.execute(
        "INSERT INTO decisions (customer_id, at, trigger, chooser, reason, rule_version, validation_failures) "
        "VALUES (?, ?, 'cart_abandoned', 'rules', 'earlier', 1, '[]')",
        (customer_id, at.isoformat(timespec="seconds")),
    )
    conn.commit()


def test_on_hour_sweeps_only_at_10(world, monkeypatch):
    calls = []
    monkeypatch.setattr(
        daily_sweep, "sweep", lambda conn, now: calls.append(now) or Counter({"sweep.offer": 2})
    )
    rep = report()
    for hour in range(1, 49):
        daily_sweep.on_hour(world, clock.START + timedelta(hours=hour), rep)
    assert calls == [NOW, NOW + timedelta(days=1)]
    assert rep.counts == Counter({"sweep.offer": 4})


def test_sweep_decides_every_customer_once_chat_attached_first(world):
    everyone = ids(world)
    chat = everyone[-3:]
    attach(world, chat)
    counts = daily_sweep.sweep(world, NOW)
    rows = sweep_decisions(world)
    assert [r["customer_id"] for r in rows[:3]] == chat
    assert sorted(r["customer_id"] for r in rows) == everyone
    assert all(r["at"] == NOW.isoformat() for r in rows)
    # No Offer Decisions are logged too.
    no_offer = sum(r["offer_id"] is None for r in rows)
    assert no_offer and counts["sweep.no_offer"] == no_offer
    assert counts["sweep.offer"] == len(rows) - no_offer


def test_the_rest_are_shuffled_by_date(world):
    one = daily_sweep.sweep_order(world, NOW)
    assert one == daily_sweep.sweep_order(world, NOW + timedelta(hours=5))
    assert one != daily_sweep.sweep_order(world, NOW + timedelta(days=1))
    assert one != ids(world) and sorted(one) == ids(world)


def free_shipping_only(es, state, catalog, rules) -> Proposal:
    """A chooser that sends free shipping whenever the Eligible Set still has it."""
    if es.send_window is None or not any(o.offer_type == OfferType.FREE_SHIPPING for o in es.options):
        return Proposal(None, reason="No Offer: free shipping not eligible")
    focus = rules_chooser.focus_category(state, es.at, catalog)
    featured = rules_chooser.featured_products(state, es.at, catalog, focus)
    caption = rules_chooser.caption(OfferType.FREE_SHIPPING, featured, focus, catalog)
    return Proposal(OfferType.FREE_SHIPPING, None, {}, featured, es.send_window[0], caption, "test")


def test_chat_attached_customers_get_the_budget_first(world, monkeypatch):
    rules = RuleSet(weekly_budget=3 * RuleSet().shipping_fee)  # room for 3 free-shipping Offers
    save_rules(world, rules, author="test")
    budget = BudgetState(week_start(NOW), 0.0, 0.0)
    catalog = load_catalog(world)
    states = load_customer_states(world, ids(world), NOW)
    eligible = [
        cid
        for cid, state in states.items()
        if eligible_set(state, rules, budget, NOW, catalog).send_window is not None
    ]
    chat = eligible[-3:]
    attach(world, chat)
    monkeypatch.setattr(pipeline, "default_chooser", lambda state, trigger=None: free_shipping_only)

    counts = daily_sweep.sweep(world, NOW)
    offered = [
        r[0] for r in world.execute("SELECT customer_id FROM offers WHERE created_at = ?", (NOW.isoformat(),))
    ]
    assert sorted(offered) == sorted(chat)
    assert counts["sweep.offer"] == 3
    assert counts["sweep.no_offer"] == len(states) - 3


def test_skips_customers_decided_in_the_last_24_hours(world, monkeypatch):
    a, b, c = ids(world)[:3]
    add_decision(world, a, NOW - timedelta(hours=23))
    add_decision(world, b, NOW - timedelta(hours=24))  # yesterday's sweep: not skipped
    add_decision(world, c, NOW + timedelta(hours=1))  # after `now`: not skipped
    counts = daily_sweep.sweep(world, NOW)
    swept = {r["customer_id"] for r in sweep_decisions(world)}
    assert a not in swept and {b, c} <= swept
    assert counts["sweep.skipped"] == 1
    assert len(swept) == len(ids(world)) - 1


def test_a_second_sweep_the_same_day_decides_nobody(world):
    daily_sweep.sweep(world, NOW)
    counts = daily_sweep.sweep(world, NOW + timedelta(hours=2))
    assert counts == Counter({"sweep.skipped": len(ids(world))})


def test_counts_in_the_report_by_outcome_and_binding_rule(world):
    rep = report()
    daily_sweep.on_hour(world, NOW, rep)
    rows = sweep_decisions(world)
    assert rep.counts["sweep.offer"] + rep.counts["sweep.no_offer"] == len(ids(world))
    bindings = Counter(f"sweep.binding.{r['binding_rule']}" for r in rows if r["binding_rule"])
    assert bindings and {k: v for k, v in rep.counts.items() if k.startswith("sweep.binding.")} == bindings


@pytest.mark.slow
def test_sweep_over_10k_customers_under_60_seconds(tmp_path):
    from offer_engine.sim.generate import run

    conn = connect(tmp_path / "big.db")
    run(conn, 10_000, months=12, seed=7)
    started = time.perf_counter()
    counts = daily_sweep.sweep(conn, NOW)
    elapsed = time.perf_counter() - started
    conn.close()
    assert counts["sweep.offer"] + counts["sweep.no_offer"] == 10_000
    print(f"sweep: {elapsed:.1f} s")
    assert elapsed < 60
