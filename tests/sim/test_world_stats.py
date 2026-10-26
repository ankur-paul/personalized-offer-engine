"""World charts' data (T41) on a hand-built database, with T27's helpers."""

import pytest

from offer_engine import clock, personas
from offer_engine.domain import RuleSet
from offer_engine.sim.live_metrics import funnel
from offer_engine.sim.world_stats import GROUPS, by_response_class, decisions_by_day, group_of, world_stats
from tests.sim.test_live_metrics import IDS, TREATED, add_customer, add_event, add_offer


@pytest.fixture
def db(conn):
    for cid in IDS:
        add_customer(conn, cid)
    add_customer(conn, "C00001-t42", tester_copy=True)
    conn.execute(
        "UPDATE sim_response_class SET response_class = 'sure_thing' WHERE customer_id = ?", (TREATED[1],)
    )
    conn.execute(
        "UPDATE sim_response_class SET response_class = 'lost_cause' WHERE customer_id = ?", (TREATED[2],)
    )
    return conn


def decide(conn, cid, at, *, offer_type=None, binding_rule=None, chooser="rules", trigger="daily_sweep"):
    offer_id = None
    if offer_type:
        offer_id = add_offer(conn, cid, at=at)
        conn.execute("UPDATE offers SET offer_type = ? WHERE id = ?", (offer_type, offer_id))
    conn.execute(
        "INSERT INTO decisions (customer_id, at, trigger, chooser, offer_id, binding_rule, rule_version)"
        " VALUES (?, ?, ?, ?, ?, ?, 0)",
        (cid, at, trigger, chooser, offer_id, binding_rule),
    )


def test_group_of_sorts_offers_and_no_offers():
    assert group_of("pct_category", "max_pct_by_loyalty_tier") == "paid"
    assert group_of("nudge", None) == "nudge"
    assert group_of(None, None) == "nothing"
    assert group_of(None, "frequency_cap_count") == "frequency_cap"
    assert group_of(None, "weekly_budget") == "budget"
    assert group_of(None, "holdout_pct") == "other_rules"


def test_days_add_up_to_each_days_decisions_with_their_details(db):
    day1, day2 = "2026-12-01T10:00:00", "2026-12-02T10:00:00"
    decide(db, "C00002", day1, offer_type="free_shipping")
    decide(db, "C00003", day1, offer_type="nudge")
    decide(db, "C00004", day1)
    decide(db, "C00005", day2, binding_rule="frequency_cap_count")
    decide(db, "C00006", day2, binding_rule="holdout_pct")
    decide(db, "C00007", day2, binding_rule="weekly_budget")
    decide(db, "C00001-t42", day2, offer_type="nudge")  # Tester copy: left out
    decide(db, "C00008", "2026-11-30T10:00:00", offer_type="nudge")  # before the clock start

    days = decisions_by_day(db)
    assert [d["day"] for d in days] == ["2026-12-01", "2026-12-02"]
    assert days[0]["groups"] == {
        "paid": 1,
        "nudge": 1,
        "nothing": 1,
        "frequency_cap": 0,
        "budget": 0,
        "other_rules": 0,
    }
    assert days[0]["offers"] == {"free_shipping": 1, "nudge": 1} and days[0]["no_offer"] == {"none": 1}
    assert days[1]["groups"] == {
        "paid": 0,
        "nudge": 0,
        "nothing": 0,
        "frequency_cap": 1,
        "budget": 1,
        "other_rules": 1,
    }
    assert days[1]["no_offer"] == {"frequency_cap_count": 1, "holdout_pct": 1, "weekly_budget": 1}
    assert list(days[1]["groups"]) == list(GROUPS)


def test_response_classes_split_customers_offers_and_spend(db):
    add_offer(db, TREATED[0])  # persuadable, paid
    add_offer(db, TREATED[1], cost=120.0)  # sure thing, redeemed
    nudge = add_offer(db, TREATED[2])  # lost cause
    db.execute("UPDATE offers SET offer_type = 'nudge' WHERE id = ?", (nudge,))
    add_offer(db, "C00001-t42", cost=500.0)  # Tester copy: left out
    add_offer(db, TREATED[3], source="history_random", at="2026-11-20T10:00:00")  # history: left out

    rows = {r["response_class"]: r for r in by_response_class(db)}
    assert sum(r["customers"] for r in rows.values()) == len(IDS)
    assert (rows["persuadable"]["paid"], rows["persuadable"]["nudges"]) == (1, 0)
    assert (rows["sure_thing"]["paid"], rows["sure_thing"]["spend"]) == (1, 120.0)
    assert (rows["lost_cause"]["paid"], rows["lost_cause"]["nudges"]) == (0, 1)
    assert rows["sleeping_dog"] == {
        "response_class": "sleeping_dog",
        "customers": 0,
        "paid": 0,
        "nudges": 0,
        "spend": 0.0,
    }


def test_world_stats_has_every_section_and_reuses_the_funnel(db, monkeypatch):
    card = personas.PersonaCard("C00002", "cart_abandoner", "Kavya Joshi", "…", True, "", 7, 40)
    monkeypatch.setattr(personas, "load_all", lambda: [card])
    db.execute("INSERT INTO chats (customer_id, chat_id, kind) VALUES ('C00002', 1, 'bot')")
    db.execute("INSERT INTO chats (customer_id, chat_id, kind) VALUES ('C00001-t42', 42, 'tester')")
    decide(db, "C00002", "2026-12-01T10:00:00", offer_type="pct_category", chooser="agent")
    decide(db, "C00002", "2026-12-02T10:00:00", binding_rule="frequency_cap_count")
    decide(db, "C00003", "2026-12-02T10:00:00", chooser="fallback", offer_type="free_shipping")
    add_event(db, TREATED[0], "order")

    stats = world_stats(db, clock.START, RuleSet())
    assert set(stats) == {"time", "since", "days", "funnel", "holdout", "truth", "choosers", "chats"}
    f = funnel(db)
    assert (stats["funnel"]["sent"], stats["funnel"]["claimed"], stats["funnel"]["redeemed"]) == (
        f.sent,
        f.claimed,
        f.redeemed,
    )
    assert stats["holdout"]["treated"]["orders"] == 1 and stats["holdout"]["pct"] == 10.0
    assert stats["choosers"] == {"agent": 1, "fallback": 1, "rules": 1}
    tester, bot = stats["chats"]  # by Customer ID
    assert (bot["name"], bot["case"], bot["kind"], bot["decisions"], bot["offers"]) == (
        "Kavya Joshi",
        "Cart abandoner",
        "bot",
        2,
        1,
    )
    assert bot["latest"]["binding_rule"] == "frequency_cap_count" and bot["latest"]["offer_type"] is None
    assert (tester["kind"], tester["name"], tester["decisions"], tester["latest"]) == (
        "tester",
        None,
        0,
        None,
    )
