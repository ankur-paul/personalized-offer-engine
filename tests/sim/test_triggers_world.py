"""Event Triggers (T19) firing Decisions as the live world runs, on a generated 200-Customer world."""

from collections import Counter

from offer_engine.db import connect
from offer_engine.sim.generate import run
from offer_engine.sim.world import day_step


def test_three_days_of_the_world_fire_decisions_through_the_triggers(tmp_path):
    conn = connect(tmp_path / "world.db")
    run(conn, 200, months=3, seed=11)
    report = day_step.advance(conn, 72)

    logged = Counter(row[0] for row in conn.execute("SELECT trigger FROM decisions"))
    assert logged["cart_abandoned"] > 0 and logged["long_gap"] > 0
    assert {f"decisions.{kind}": n for kind, n in logged.items()} == {
        k: v for k, v in report.counts.items() if k.startswith("decisions.")
    }
    assert report.counts["decisions.cart_abandoned"] == report.counts["cart_abandoned"]
    fired = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT customer_id || kind || key) FROM trigger_log"
    ).fetchone()
    assert fired[0] == fired[1] == sum(logged.values())
    conn.close()
