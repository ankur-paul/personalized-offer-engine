"""Preview impact of a Rule change (T28) on a 300-Customer world: one Daily Sweep under the current and the edited
Rules, each on its own copy of the database."""

import hashlib
import shutil
import sys
import types
from collections import Counter
from datetime import datetime

import pytest

from offer_engine import clock, rules_store
from offer_engine.db import connect
from offer_engine.domain import RuleSet
from offer_engine.lift import segment_lift
from offer_engine.sim import preview as preview_mod
from offer_engine.sim.preview import PreviewResult, SweepSummary, next_sweep, preview


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    from offer_engine.sim.generate import run

    path = tmp_path_factory.mktemp("preview") / "world.db"
    conn = connect(path)
    run(conn, 300, months=6, seed=7)
    segment_lift.fit(conn)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    return path


@pytest.fixture
def live(template, tmp_path):
    path = tmp_path / "world.db"
    shutil.copy(template, path)
    conn = connect(path)
    yield conn, path
    conn.close()


def preview_on(template, tmp_path_factory, rules):
    path = tmp_path_factory.mktemp("preview_on") / "world.db"
    shutil.copy(template, path)
    conn = connect(path)
    try:
        return preview(conn, rules)
    finally:
        conn.close()


@pytest.fixture(scope="module")
def holdout_raised(template, tmp_path_factory):
    """The Holdout raised from 10% to 50%, previewed once for the module."""
    return preview_on(template, tmp_path_factory, RuleSet(holdout_pct=50.0))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_raising_the_holdout_reduces_offers_and_cost(holdout_raised):
    result = holdout_raised
    assert result.current.offers > 0
    assert result.offers_delta < 0
    assert result.worst_case_delta < 0
    assert result.expected_delta < 0
    assert result.newly_blocked
    assert not result.newly_unblocked
    top = result.binding_changes()[0]
    assert (top.name, top.change > 0) == ("holdout_pct", True)


def test_raising_the_margin_floor_makes_it_the_binding_rule(template, tmp_path_factory):
    """The rules chooser's discounts sit well under the default 5% floor's limit, so a higher floor first takes
    over as the Binding Rule from the loyalty-tier caps."""
    result = preview_on(template, tmp_path_factory, RuleSet(margin_floor_pct=25.0))
    changes = {c.name: c.change for c in result.binding_changes()}
    assert changes["margin_floor_pct"] > 0
    assert changes["max_pct_by_loyalty_tier"] < 0
    assert result.worst_case_delta <= 0


def test_identical_rules_give_a_zero_diff(live):
    conn, _ = live
    result = preview(conn, rules_store.current_rules(conn)[1])
    assert result.current.offers > 0
    assert (result.offers_delta, result.worst_case_delta, result.expected_delta) == (0, 0.0, 0.0)
    assert result.newly_blocked == result.newly_unblocked == frozenset()
    assert result.type_changes() == result.binding_changes() == []


def test_the_live_database_is_untouched(live):
    conn, path = live
    before = digest(path), rules_store.current_rules(conn), clock.now(conn)
    preview(conn, RuleSet(margin_floor_pct=15.0))
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert (digest(path), rules_store.current_rules(conn), clock.now(conn)) == before
    assert not list(path.parent.glob(".preview-*"))


def test_the_sweep_runs_at_the_next_10_00(live):
    conn, _ = live
    result = preview(conn, RuleSet())
    assert result.at == next_sweep(clock.now(conn))
    assert next_sweep(datetime(2026, 12, 1, 9, 59)) == datetime(2026, 12, 1, 10, 0)
    assert next_sweep(datetime(2026, 12, 1, 10, 0)) == datetime(2026, 12, 2, 10, 0)
    assert next_sweep(datetime(2026, 12, 1, 23, 0)) == datetime(2026, 12, 2, 10, 0)


def test_the_preview_never_calls_the_agent(live, monkeypatch):
    def no_agent(*args):
        raise AssertionError("the preview must use the rules chooser")

    monkeypatch.setattr(preview_mod.pipeline, "default_chooser", no_agent)
    conn, _ = live
    conn.execute("INSERT INTO chats (customer_id, kind, chat_id) SELECT id, 'bot', 1 FROM customers LIMIT 1")
    conn.commit()
    preview(conn, RuleSet(margin_floor_pct=15.0), parallel=False)


def test_the_preview_ignores_the_callers_main_module(live, monkeypatch, tmp_path):
    """Streamlit runs each console page as `__main__`; the sweeps' child processes must not rerun it."""
    script = tmp_path / "page.py"
    script.write_text("raise SystemExit('a child process ran the caller's __main__')\n")
    page = types.ModuleType("__main__")
    page.__file__ = str(script)
    monkeypatch.setitem(sys.modules, "__main__", page)
    conn, _ = live
    assert preview(conn, RuleSet(holdout_pct=50.0)).offers_delta < 0


def test_a_failed_sweep_raises_with_its_error(live, monkeypatch):
    monkeypatch.setattr(preview_mod.sys, "executable", "/bin/false")
    conn, _ = live
    with pytest.raises(RuntimeError, match="the preview sweep on current.db failed"):
        preview(conn, RuleSet(holdout_pct=50.0))


def summary(offers, worst, expected, types=(), binding=(), offered=()):
    return SweepSummary(offers, worst, expected, Counter(types), Counter(binding), frozenset(offered))


def test_headline_and_change_tables():
    result = PreviewResult(
        datetime(2026, 12, 2, 10, 0),
        summary(
            2_000,
            100_000.0,
            20_000.0,
            {"pct_category": 1_500, "nudge": 500},
            {"margin_floor_pct": 300},
            offered={"C1", "C2"},
        ),
        summary(
            3_240,
            138_200.0,
            26_100.0,
            {"pct_category": 2_740, "nudge": 500},
            {"margin_floor_pct": 100, "weekly_budget": 50},
            offered={"C2", "C3", "C4"},
        ),
    )
    assert result.headline() == "+1,240 Offers · +₹38,200 worst-case cost · +₹6,100 expected cost"
    assert result.newly_blocked == {"C1"}
    assert result.newly_unblocked == {"C3", "C4"}
    assert [(c.name, c.current, c.new, c.change) for c in result.type_changes()] == [
        ("pct_category", 1_500, 2_740, 1_240)
    ]
    assert [(c.name, c.change) for c in result.binding_changes()] == [
        ("margin_floor_pct", -200),
        ("weekly_budget", 50),
    ]
    fewer = PreviewResult(result.at, result.new, result.current)
    assert fewer.headline() == "-1,240 Offers · -₹38,200 worst-case cost · -₹6,100 expected cost"
