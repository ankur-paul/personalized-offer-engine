"""Showcase Customer selection on the 2,000-Customer world (T23, PLAN §4.2)."""

import sqlite3
from datetime import datetime, timedelta

import pytest

from offer_engine import clock
from offer_engine.domain import RuleSet
from offer_engine.personas import CASES
from offer_engine.rules import in_holdout
from offer_engine.sim.personas.select import (
    CART_ABANDONS,
    EXPIRING_WITHIN_DAYS,
    NO_HELP_CLASSES,
    OFFER_CASES,
    select_showcase,
)

NOW = clock.START
RULES = RuleSet()


@pytest.fixture(scope="module")
def picks(world_2k):
    conn, _ = world_2k
    return {p.case: p.customer_id for p in select_showcase(conn, RULES, NOW)}


@pytest.fixture
def world_2k_copy(world_2k, tmp_path):
    """A writable copy of the 2,000-Customer world."""
    conn, _ = world_2k
    copy = sqlite3.connect(tmp_path / "copy.db")
    conn.backup(copy)
    copy.row_factory = sqlite3.Row
    yield copy
    copy.close()


def response_class(conn, customer_id):
    return conn.execute(
        "SELECT response_class FROM sim_response_class WHERE customer_id = ?", (customer_id,)
    ).fetchone()[0]


def test_every_case_gets_a_distinct_customer(picks):
    assert list(picks) == list(CASES)
    assert len(set(picks.values())) == len(CASES)


def test_holdout_pick_is_in_the_holdout_and_no_other_is(picks):
    assert in_holdout(picks["holdout"], RULES.holdout_pct)
    assert not any(in_holdout(cid, RULES.holdout_pct) for case, cid in picks.items() if case != "holdout")


def test_sure_thing_pick_has_that_class(world_2k, picks):
    conn, _ = world_2k
    assert response_class(conn, picks["sure_thing"]) == "sure_thing"
    assert response_class(conn, picks["persuadable"]) == "persuadable"


def test_offer_cases_skip_customers_an_offer_cant_help(world_2k, picks):
    conn, _ = world_2k
    assert all(response_class(conn, picks[case]) not in NO_HELP_CLASSES for case in OFFER_CASES)


def test_picks_meet_their_case(world_2k, picks):
    conn, _ = world_2k
    orders = conn.execute(
        "SELECT COUNT(*) FROM events WHERE customer_id = ? AND kind = 'order'", (picks["new_one_order"],)
    ).fetchone()[0]
    assert orders == 1
    expires = conn.execute(
        "SELECT points_expire_at FROM customers WHERE id = ?", (picks["expiring_points"],)
    ).fetchone()[0]
    assert NOW < datetime.fromisoformat(expires) <= NOW + timedelta(days=EXPIRING_WITHIN_DAYS)
    abandons = conn.execute(
        "SELECT COUNT(*) FROM events WHERE customer_id = ? AND kind = 'cart_abandoned' AND at >= ?",
        (picks["cart_abandoner"], (NOW - timedelta(days=30)).isoformat()),
    ).fetchone()[0]
    assert CART_ABANDONS[0] <= abandons <= CART_ABANDONS[1]
    redeemed = conn.execute(
        "SELECT COUNT(*) FROM offers WHERE customer_id = ? AND status = 'redeemed'", (picks["deal_hunter"],)
    ).fetchone()[0]
    assert redeemed >= 2


def test_selection_is_deterministic(world_2k, picks):
    conn, _ = world_2k
    assert {p.case: p.customer_id for p in select_showcase(conn, RULES, NOW)} == picks


def test_missing_required_case_raises(world_2k_copy):
    world_2k_copy.execute(
        "UPDATE sim_response_class SET response_class = 'lost_cause' WHERE response_class = 'sure_thing'"
    )
    with pytest.raises(ValueError, match="sure_thing"):
        select_showcase(world_2k_copy, RULES, NOW)


def test_persuadable_is_optional(world_2k_copy):
    world_2k_copy.execute(
        "UPDATE sim_response_class SET response_class = 'lost_cause' WHERE response_class = 'persuadable'"
    )
    cases = [p.case for p in select_showcase(world_2k_copy, RULES, NOW)]
    assert cases == [c for c in CASES if c != "persuadable"]
