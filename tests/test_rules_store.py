from datetime import datetime

import pytest

from offer_engine import clock
from offer_engine.domain import RuleSet
from offer_engine.rules_store import current_rules, list_versions, revert, rules_at_version, save_rules


def test_defaults_at_version_zero(conn):
    assert current_rules(conn) == (0, RuleSet())
    assert list_versions(conn) == []


def test_save_then_revert(conn):
    strict = RuleSet(margin_floor_pct=12.0, weekly_budget=10_000.0)
    assert save_rules(conn, strict, author="Priya", note="tighter margins") == 1
    assert current_rules(conn) == (1, strict)

    loose = RuleSet(frequency_cap_count=5)
    assert save_rules(conn, loose, author="Rahul") == 2
    assert current_rules(conn) == (2, loose)

    assert revert(conn, 1, author="Priya") == 3
    assert current_rules(conn) == (3, strict)
    assert rules_at_version(conn, 2) == loose


def test_list_versions_newest_first_with_who_and_when(conn):
    clock.advance(conn, 30)
    save_rules(conn, RuleSet(), author="Priya", note="first")
    revert(conn, 0, author="Rahul")
    versions = list_versions(conn)
    assert [v.version for v in versions] == [2, 1]
    assert (versions[0].author, versions[0].note) == ("Rahul", "revert to v0")
    assert versions[1].created_at == datetime(2026, 12, 2, 6, 0)
    assert all(v.rules == RuleSet() for v in versions)


def test_revert_unknown_version(conn):
    with pytest.raises(ValueError, match="no rule version 7"):
        revert(conn, 7, author="Priya")
