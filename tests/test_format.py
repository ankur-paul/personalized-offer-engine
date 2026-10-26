"""`fetch_decisions`, the Decision query shared by `decisions`, `trigger` and the live view's ticker (T44)."""

from __future__ import annotations

from datetime import timedelta

from offer_engine import clock, pipeline
from offer_engine.commands._format import fetch_decisions
from offer_engine.domain import Chooser, TriggerKind

NOW = clock.START + timedelta(hours=10)


def decide_as(world, choosers: list[Chooser]) -> list[int]:
    """One Decision per chooser, for different Customers, each marked as made by that chooser."""
    customers = [
        r[0] for r in world.execute("SELECT id FROM customers ORDER BY id LIMIT ?", (len(choosers),))
    ]
    ids = []
    for customer_id, chooser in zip(customers, choosers, strict=True):
        decision = pipeline.decide(world, customer_id, TriggerKind.CART_ABANDONED, NOW)
        world.execute("UPDATE decisions SET chooser = ? WHERE id = ?", (str(chooser), decision.id))
        ids.append(decision.id)
    world.commit()
    return ids


def test_choosers_keeps_only_those_newest_first(world):
    agent, rules, fallback, rules2, agent2 = decide_as(
        world, [Chooser.AGENT, Chooser.RULES, Chooser.FALLBACK, Chooser.RULES, Chooser.AGENT]
    )
    rows = fetch_decisions(world, choosers=[Chooser.AGENT, Chooser.FALLBACK])
    assert [r["id"] for r in rows] == [agent2, fallback, agent]
    assert [r["id"] for r in fetch_decisions(world, choosers=[Chooser.RULES])][:2] == [rules2, rules]


def test_last_counts_after_the_filter(world):
    agent, *_ = decide_as(world, [Chooser.AGENT, Chooser.RULES, Chooser.RULES, Chooser.RULES])
    # The agent Decision is 4th newest, so `last=1` finds it only if the limit applies after the filter.
    assert [r["id"] for r in fetch_decisions(world, last=1, choosers=[Chooser.AGENT])] == [agent]


def test_no_choosers_keeps_every_decision(world):
    ids = decide_as(world, [Chooser.AGENT, Chooser.RULES])
    assert [r["id"] for r in fetch_decisions(world, last=2)] == ids[::-1]
