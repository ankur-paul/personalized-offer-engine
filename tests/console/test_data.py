import threading
from collections import Counter
from datetime import datetime

from console import data
from offer_engine import clock
from offer_engine.db import connect


def ids(frame):
    return frame["id"].tolist()


def test_newest_first_and_no_offer_hidden_by_default(decision_db):
    frame = data.decisions(decision_db)
    assert frame["customer"].tolist() == ["C00003", "C00002", "C00001"]
    assert ids(frame) == sorted(ids(frame), reverse=True)
    assert len(data.decisions(decision_db, hide_no_offer=False)) == 4


def test_filters_by_customer_trigger_and_chooser(decision_db):
    assert data.decisions(decision_db, customer_id="C00002", hide_no_offer=False)["trigger"].tolist() == [
        "daily_sweep",
        "long_gap",
    ]
    assert data.decisions(decision_db, trigger="daily_sweep")["customer"].tolist() == ["C00002"]
    assert data.decisions(decision_db, chooser="fallback")["customer"].tolist() == ["C00003"]
    assert data.decisions(decision_db, trigger="long_gap").empty
    assert data.decisions(decision_db, customer_id="C00001", chooser="agent").empty


def test_limit_keeps_the_newest(decision_db):
    assert data.decisions(decision_db, hide_no_offer=False, limit=2)["customer"].tolist() == [
        "C00003",
        "C00002",
    ]


def test_row_shows_reason_binding_rule_version_and_validation(decision_db):
    rows = data.decisions(decision_db, hide_no_offer=False).set_index("customer", drop=False)
    offer = data.decisions(decision_db, customer_id="C00001").iloc[0]
    assert offer["time"] == "2026-12-01 10:00"
    assert offer["offer"] == "pct_category fashion pct=12 cap=170"
    assert (offer["chooser"], offer["reason"]) == ("rules", "best Lift × margin")
    assert (offer["binding_rule"], offer["rule_version"], offer["validation"]) == (
        "max_pct_by_loyalty_tier",
        0,
        "valid",
    )
    assert (offer["code"], offer["status"], offer["caption"]) == (
        "POE-C0000110",
        "queued",
        "Fashion picks for you",
    )

    no_offer = data.decisions(decision_db, trigger="long_gap", hide_no_offer=False).iloc[0]
    assert (no_offer["offer"], no_offer["validation"], no_offer["code"]) == (
        "No Offer",
        "nothing to validate",
        "",
    )

    fallback = rows.loc["C00003"]
    assert fallback["validation"] == "valid (Fallback)"
    assert fallback["failures"] == ["pct 40 above max 15 (max_pct_by_loyalty_tier)"]
    assert fallback["agent_output"] == '{"option": "pct_category"}'


def test_empty_log_has_the_columns(conn):
    frame = data.decisions(conn)
    assert frame.empty and list(frame.columns) == data.DECISION_COLUMNS


def test_counts_frame_orders_events_then_hooks():
    counts = Counter({"decisions.long_gap": 2, "order": 3, "session": 40, "offers_sent": 0, "decisions.a": 1})
    frame = data.counts_frame(counts)
    assert frame["what"].tolist() == ["session", "order", "decisions.a", "decisions.long_gap"]
    assert frame["count"].tolist() == [40, 3, 1, 2]


def test_advance_runs_the_day_step(world, monkeypatch):
    monkeypatch.setenv("SEED", "3")
    report = data.advance(world, 24)
    assert clock.now(world) == datetime(2026, 12, 2) == report.end
    assert report.counts["session"] > 0


def test_advance_skips_while_another_step_runs(world, tmp_path):
    started, release = threading.Event(), threading.Event()
    real_advance = data.day_step.advance

    def slow(conn, hours, seed):
        started.set()
        release.wait(5)
        return real_advance(conn, hours, seed)

    data.day_step.advance = slow
    try:

        def run_one_hour():
            other = connect(tmp_path / "world.db")
            data.advance(other, 1)
            other.close()

        worker = threading.Thread(target=run_one_hour)
        worker.start()
        assert started.wait(5)
        assert data.advance(world, 24) is None
        release.set()
        worker.join(10)
    finally:
        data.day_step.advance = real_advance
    assert clock.now(world) == datetime(2026, 12, 1, 1)


def test_rule_history_lists_what_each_version_changed(conn):
    from offer_engine import rules_store
    from offer_engine.domain import RuleSet

    rules_store.save_rules(conn, RuleSet(margin_floor_pct=10.0), "Asha", "protect margins")
    rules_store.save_rules(conn, RuleSet(margin_floor_pct=10.0, holdout_pct=20.0), "Ravi", "bigger Holdout")
    rules_store.revert(conn, 1, "Asha")
    rules_store.save_rules(conn, RuleSet(margin_floor_pct=10.0), "Asha", "no-op")
    history = data.rule_history(conn)
    assert list(history.columns) == data.HISTORY_COLUMNS
    assert history["version"].tolist() == [4, 3, 2, 1, 0]
    assert history["changed"].tolist() == ["(none)", "holdout_pct", "holdout_pct", "margin_floor_pct", ""]
    assert history["note"].tolist() == [
        "no-op",
        "revert to v1",
        "bigger Holdout",
        "protect margins",
        "defaults",
    ]
