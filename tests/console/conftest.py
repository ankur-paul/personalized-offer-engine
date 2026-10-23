import json

import pytest


def add_decision(
    conn,
    customer_id,
    at,
    trigger="cart_abandoned",
    chooser="rules",
    offer=True,
    failures=(),
    agent_output=None,
):
    """Insert a Decision, with a queued `pct_category` Offer unless `offer` is False. Returns its ID."""
    offer_id = None
    if offer:
        offer_id = conn.execute(
            "INSERT INTO offers (code, customer_id, offer_type, category, params, created_at, send_at, expires_at,"
            " caption, rule_version, worst_case_cost, expected_cost, status, source)"
            " VALUES (?, ?, 'pct_category', 'fashion', '{\"pct\": 12, \"cap\": 170}', ?, ?, ?, 'Fashion picks for you',"
            " 0, 170, 20, 'queued', 'live')",
            (f"POE-{customer_id[-6:]}{at[11:13]}", customer_id, at, at, at),
        ).lastrowid
    decision_id = conn.execute(
        "INSERT INTO decisions (customer_id, at, trigger, chooser, offer_id, reason, binding_rule, rule_version,"
        " validation_ok, validation_failures, agent_output) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
        (
            customer_id,
            at,
            trigger,
            chooser,
            offer_id,
            "best Lift × margin",
            "max_pct_by_loyalty_tier" if offer else None,
            None if not offer else 1,
            json.dumps(list(failures)),
            agent_output,
        ),
    ).lastrowid
    conn.commit()
    return decision_id


@pytest.fixture
def decision_db(world):
    """The 50-Customer world with four Decisions: two Offers, one No Offer, one Fallback."""
    add_decision(world, "C00001", "2026-12-01T10:00:00")
    add_decision(world, "C00002", "2026-12-01T11:00:00", trigger="long_gap", offer=False)
    add_decision(world, "C00002", "2026-12-01T12:00:00", trigger="daily_sweep")
    add_decision(
        world,
        "C00003",
        "2026-12-01T13:00:00",
        chooser="fallback",
        failures=["pct 40 above max 15 (max_pct_by_loyalty_tier)"],
        agent_output='{"option": "pct_category"}',
    )
    return world
