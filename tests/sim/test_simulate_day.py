import copy
from dataclasses import replace
from datetime import date, datetime, timedelta

import numpy as np
import pytest

from offer_engine.sim.generate import CustomerSim, GenContext, catalog, customers
from offer_engine.sim.generate.history import EVENT_KINDS, simulate_day

DAY = date(2026, 11, 3)


@pytest.fixture
def ctx(conn):
    """60 Customers who all signed up before DAY, with busy traits so the day has plenty of events."""
    context = GenContext(conn, seed=5, n_customers=60, start=date(2025, 12, 1), end=date(2026, 12, 1))
    catalog.step(context)
    customers.step(context)
    context.customers = [c for c in context.customers if c.signup_at < datetime(2026, 11, 1)]
    for customer in context.customers:
        context.state[customer.id].churned_at = None
        context.traits[customer.id] = replace(context.traits[customer.id], visit_rate=3.0, buy_propensity=3.0)
    context.conn = None  # simulate_day must not need the database
    return context


def test_one_day_yields_only_listed_kinds_inside_the_day(ctx):
    events = simulate_day(ctx, DAY, np.random.default_rng(1))
    assert {e.kind for e in events} >= {"session", "product_view", "add_to_cart", "order"}
    assert {e.kind for e in events} <= set(EVENT_KINDS)
    day_start = datetime.combine(DAY, datetime.min.time())
    assert all(day_start <= e.at < day_start + timedelta(days=1) for e in events)
    assert [e.at for e in events] == sorted(e.at for e in events)
    known = {c.id for c in ctx.customers}
    assert all(e.customer_id in known for e in events)


def test_orders_schedule_delivery_three_days_later(ctx):
    rng = np.random.default_rng(2)
    orders = [e for e in simulate_day(ctx, DAY, rng) if e.kind == "order"]
    for offset in (1, 2):
        simulate_day(ctx, DAY + timedelta(days=offset), rng)
    delivered = [e for e in simulate_day(ctx, DAY + timedelta(days=3), rng) if e.kind == "delivered"]
    assert sorted((e.customer_id, e.at - timedelta(days=3), e.amount) for e in delivered) == sorted(
        (e.customer_id, e.at, e.amount) for e in orders
    )
    earned = [e for e in simulate_day(ctx, DAY + timedelta(days=4), rng) if e.kind == "points_earned"]
    assert earned  # later deliveries earn points


def test_points_expire_whole_balance_on_the_expiry_day(ctx):
    customer_id = ctx.customers[0].id
    ctx.traits[customer_id] = replace(ctx.traits[customer_id], visit_rate=0.0)
    sim = ctx.state[customer_id]
    sim.points_balance, sim.points_expire_at = (
        420,
        datetime.combine(DAY, datetime.min.time()) + timedelta(hours=9),
    )
    expired = [e for e in simulate_day(ctx, DAY, np.random.default_rng(3)) if e.customer_id == customer_id]
    assert [(e.kind, e.amount, e.at.hour) for e in expired] == [("points_expired", 420.0, 9)]
    assert (sim.points_balance, sim.points_expire_at) == (0, None)


def test_customers_who_have_not_signed_up_do_nothing(ctx):
    future = replace(ctx.customers[0], signup_at=datetime(2026, 12, 25))
    ctx.customers[0] = future
    ctx.state[future.id] = CustomerSim()
    events = simulate_day(ctx, DAY, np.random.default_rng(4))
    assert all(e.customer_id != future.id for e in events)


def test_same_state_and_seed_give_the_same_day(ctx):
    twin = copy.deepcopy(ctx)
    first = simulate_day(ctx, DAY, np.random.default_rng(9))
    assert first and first == simulate_day(twin, DAY, np.random.default_rng(9))
    assert ctx.state == twin.state
