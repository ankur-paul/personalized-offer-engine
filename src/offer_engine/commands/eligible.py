"""`offer-engine eligible --demo | --customer ID`: print the Eligible Set and Binding Rules for a Customer."""

from __future__ import annotations

import argparse

TIME_FORMAT = "%Y-%m-%d %H:%M"
MONEY_PARAMS = {"cap", "amount", "min_basket"}


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("eligible", help="print the Eligible Set and Binding Rules for a Customer")
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument(
        "--demo", action="store_true", help="a built-in fixture Customer under the default Rules"
    )
    who.add_argument(
        "--customer", metavar="ID", help="a Customer from the database, at clock now under the current Rules"
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from offer_engine.domain import RuleSet
    from offer_engine.rules import eligible_set

    if args.customer:
        state, budget, now, catalog, version, rules = from_database(args.customer)
        rules_label = f"rule v{version}"
    else:
        state, budget, now, catalog = demo_fixture()
        rules, rules_label = RuleSet(), "default Rules"
    es = eligible_set(state, rules, budget, now, catalog)
    remaining = rules.weekly_budget - budget.spent - budget.reserved
    print(f"Eligible Set for {es.customer_id} ({state.customer.loyalty_tier}) at {now.strftime(TIME_FORMAT)}")
    print(f"{rules_label} · budget left this week ₹{remaining:,.0f} of ₹{rules.weekly_budget:,.0f}")
    if es.short_circuit:
        print(f"No Offer: {es.short_circuit} (binding: {es.binding_rule})")
        return 0
    if es.send_window:
        start, end = es.send_window
        print(f"send window {start.strftime(TIME_FORMAT)} – {end.strftime(TIME_FORMAT)}")
    else:
        print("send window: none left")
    print()
    for opt in es.options:
        limits = "  ".join(
            f"{name} {_range(name, r.lo, r.hi)} (binding: {opt.binding_rules[name]})"
            for name, r in opt.ranges.items()
        )
        print(f"{opt.offer_type:<18} {opt.category or '':<12} worst ₹{opt.worst_case_cost:<6,.0f} {limits}")
    for key, rule in es.dropped.items():
        offer_type, _, category = key.partition(":")
        print(f"{offer_type:<18} {category:<12} dropped (binding: {rule})")
    return 0


def _range(name: str, lo: float, hi: float) -> str:
    unit = "₹" if name in MONEY_PARAMS else ""
    if hi == float("inf"):
        return f"≥ {unit}{lo:,.0f}"
    fmt = ",.0f" if unit else "g"
    return f"{unit}{lo:{fmt}}–{unit}{hi:{fmt}}"


def from_database(customer_id: str):
    from offer_engine import clock
    from offer_engine.budget import budget_state
    from offer_engine.customers import load_customer_state
    from offer_engine.db import connect, load_catalog
    from offer_engine.rules_store import current_rules

    conn = connect()
    now = clock.now(conn)
    try:
        state = load_customer_state(conn, customer_id, now)
    except KeyError:
        raise SystemExit(f"no Customer {customer_id}; run `offer-engine generate` first?") from None
    version, rules = current_rules(conn)
    budget = budget_state(conn, rules, now)
    catalog = load_catalog(conn)
    conn.close()
    return state, budget, now, catalog, version, rules


def demo_fixture():
    """A silver Customer who browsed fashion, electronics and grocery, part-way through a week's budget."""
    from datetime import datetime, timedelta

    from offer_engine import clock
    from offer_engine.domain import BudgetState, Catalog, Category, Customer, CustomerState, Event

    now = clock.START + timedelta(hours=10)
    catalog = Catalog(
        categories={
            "grocery": Category("grocery", margin_pct=15.0, avg_basket=900.0),
            "electronics": Category("electronics", margin_pct=10.0, avg_basket=6500.0),
            "fashion": Category("fashion", margin_pct=45.0, avg_basket=1800.0),
            "beauty": Category("beauty", margin_pct=40.0, avg_basket=750.0),
            "home": Category("home", margin_pct=30.0, avg_basket=2200.0),
        },
        products={},
    )
    customer = Customer(
        id="DEMO-001",
        signup_at=datetime(2026, 3, 14, 18, 0),
        city_tier=2,
        device="android",
        channel="social",
        loyalty_tier="silver",
        points_balance=420,
        points_expire_at=now + timedelta(days=20),
    )
    events = (
        Event(customer.id, now - timedelta(days=40), "order", category="electronics", amount=7200.0),
        Event(customer.id, now - timedelta(days=12), "product_view", category="grocery"),
        Event(customer.id, now - timedelta(days=3), "product_view", category="fashion"),
        Event(customer.id, now - timedelta(days=2), "add_to_cart", category="fashion"),
        Event(customer.id, now - timedelta(days=2), "cart_abandoned", category="fashion"),
    )
    budget = BudgetState(week_start=now - timedelta(days=now.weekday()), spent=12_400.0, reserved=6_100.0)
    return CustomerState(customer=customer, events=events, offers=()), budget, now, catalog
