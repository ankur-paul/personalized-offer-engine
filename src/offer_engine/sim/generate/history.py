"""History step and `simulate_day`, the per-day organic behaviour model the live world (T17) reuses.

A session views products in one category, may add one to the cart, then either orders or abandons the cart.
Orders are delivered 3 days later, which earns points; some deliveries come back as returns. Points expire
180 days after the last earn. Customers lapse at a daily hazard and then visit rarely. No Offers here.

Points events carry the number of points in `amount`; order, delivery and return events carry rupees.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING

import numpy as np

from offer_engine.domain import Event, RuleSet

if TYPE_CHECKING:
    from offer_engine.domain import Product
    from offer_engine.sim.generate import CustomerSim, GenContext
    from offer_engine.sim.generate.customers import Traits

EVENT_KINDS = (
    "session",
    "product_view",
    "add_to_cart",
    "cart_abandoned",
    "order",
    "delivered",
    "return",
    "points_earned",
    "points_burned",
    "points_expired",
)

# Funnel per category: add-to-cart chance per session (scaled by buy_propensity) and order chance given a cart.
CART_RATE = {"grocery": 0.115, "electronics": 0.026, "fashion": 0.044, "beauty": 0.062, "home": 0.031}
ORDER_GIVEN_CART = {"grocery": 0.30, "electronics": 0.14, "fashion": 0.17, "beauty": 0.24, "home": 0.16}
RETURN_RATE = {"grocery": 0.01, "electronics": 0.06, "fashion": 0.20, "beauty": 0.04, "home": 0.08}
BASKET_SIGMA = 0.45
MEAN_VIEWS = 1.0

# The signup session: many Customers sign up at checkout.
FIRST_SESSION_CART = 0.8
FIRST_SESSION_ORDER_GIVEN_CART = 0.5

DELIVERY_DAYS = 3
RETURN_DAYS = (1, 8)
ABANDON_AFTER = timedelta(minutes=60)

NEW_CUSTOMER_DAYS = 60
NEW_CUSTOMER_HAZARD = 0.025  # daily lapse chance in the first 60 days; most new Customers stay one-time
LAPSED_VISIT_FACTOR = 0.03

POINTS_PER_RUPEE = 0.1  # 1 point per ₹10, 2.5% back
SIGNUP_BONUS = 100
POINTS_VALIDITY = timedelta(days=180)
POINTS_BURN_MIN = 50
POINTS_BURN_MAX_SHARE = 0.3  # points cover at most 30% of an order
BURN_FLOOR = 0.4  # every Customer burns at least this often when they can; coupon_affinity adds the rest
WELCOME_BURN = 0.65  # in a Customer's first NEW_CUSTOMER_DAYS, the least chance of burning points on an order
POINT_VALUE = RuleSet().point_value

# Diwali 2026: festive window mid-Sep to end of Oct, peak sale week 1–7 Nov (month, day).
FESTIVE = ((9, 15), (10, 31), 1.05)
PEAK_WEEK = ((11, 1), (11, 7), 4.0)
WEEKEND = 1.1

# Session start hour weights, evening-heavy.
HOUR_WEIGHTS = np.array(
    [1, 0.5, 0.3, 0.2, 0.2, 0.3, 0.8, 1.5, 2, 2.5, 3, 3, 3.2, 3.5, 3, 3, 3.2, 3.5, 4, 4.5, 5, 5, 4, 2.5]
)
HOUR_P = HOUR_WEIGHTS / HOUR_WEIGHTS.sum()


def season(day: date) -> float:
    """Demand multiplier for a day: festive window, peak sale week and weekends."""
    multiplier = WEEKEND if day.weekday() >= 5 else 1.0
    for start, end, factor in (FESTIVE, PEAK_WEEK):
        if start <= (day.month, day.day) <= end:
            multiplier *= factor
    return multiplier


def simulate_day(ctx: GenContext, day: date, rng: np.random.Generator) -> list[Event]:
    """Organic events for every Customer on `day`, in time order. Updates `ctx.state` and `ctx.scheduled`."""
    day_start = datetime.combine(day, time())
    day_end = day_start + timedelta(days=1)
    last_second = day_end - timedelta(seconds=1)
    demand = math.sqrt(season(day))  # half on visits, half on conversion
    by_category = products_by_category(ctx)
    events: list[Event] = []

    for due in sorted(ctx.scheduled.pop(day, []), key=lambda e: (e.at, e.customer_id)):
        sim = ctx.state[due.customer_id]
        if due.kind == "delivered":
            events.extend(expire_points(sim, due.customer_id, due.at))
            events.append(due)
            events.append(earn_points(sim, due))
            if rng.random() < RETURN_RATE.get(due.category, 0.05):
                returned_at = due.at + timedelta(
                    days=int(rng.integers(*RETURN_DAYS)), minutes=int(rng.integers(0, 600))
                )
                ctx.scheduled[returned_at.date()].append(
                    Event(due.customer_id, returned_at, "return", due.category, due.product_id, due.amount)
                )
        else:
            events.append(due)

    customers = ctx.customers
    hazard_draws = rng.random(len(customers))
    rates = np.zeros(len(customers))
    for i, customer in enumerate(customers):
        if customer.signup_at >= day_start:
            continue
        sim = ctx.state[customer.id]
        traits = ctx.traits[customer.id]
        if sim.churned_at is None:
            new = (day - customer.signup_at.date()).days < NEW_CUSTOMER_DAYS
            if hazard_draws[i] < (NEW_CUSTOMER_HAZARD if new else traits.churn_hazard):
                sim.churned_at = day_start + timedelta(seconds=int(rng.integers(0, 86_400)))
        lapsed = sim.churned_at is not None and sim.churned_at < day_start
        rates[i] = traits.visit_rate * (LAPSED_VISIT_FACTOR if lapsed else 1.0) * demand
    session_counts = rng.poisson(rates)

    for i, customer in enumerate(customers):
        first = day_start <= customer.signup_at < day_end
        starts = []
        if session_counts[i]:
            hours = rng.choice(24, size=session_counts[i], p=HOUR_P)
            seconds = rng.integers(0, 3600, session_counts[i])
            starts = [day_start + timedelta(hours=int(h), seconds=int(s)) for h, s in zip(hours, seconds)]
        if first:
            starts.append(customer.signup_at)
            events.append(signup_bonus(ctx.state[customer.id], customer.id, customer.signup_at))
        welcome = (day - customer.signup_at.date()).days < NEW_CUSTOMER_DAYS
        for start in sorted(starts):
            is_signup = first and start == customer.signup_at
            events.extend(
                session(ctx, customer.id, start, last_second, by_category, demand, rng, is_signup, welcome)
            )
        events.extend(expire_points(ctx.state[customer.id], customer.id, last_second))

    events.sort(key=lambda e: e.at)
    return events


def session(
    ctx: GenContext,
    customer_id: str,
    start: datetime,
    latest: datetime,
    by_category: dict[str, list[Product]],
    demand: float,
    rng: np.random.Generator,
    first: bool,
    welcome: bool = False,
) -> list[Event]:
    """One visit, ending in nothing, an abandoned cart or an order. Times never pass `latest` (end of day)."""

    def later(at: datetime, lo: int, hi: int) -> datetime:
        return min(latest, at + timedelta(seconds=int(rng.integers(lo, hi))))

    traits: Traits = ctx.traits[customer_id]
    categories = list(traits.category_affinity)
    weights = np.array([traits.category_affinity[c] for c in categories])
    category = categories[int(rng.choice(len(categories), p=weights / weights.sum()))]
    products = by_category[category]
    at = start
    events = [Event(customer_id, at, "session", category)]
    viewed = [products[int(j)] for j in rng.integers(0, len(products), 1 + rng.poisson(MEAN_VIEWS))]
    for product in viewed:
        at = later(at, 20, 180)
        events.append(Event(customer_id, at, "product_view", category, product.id, product.price))

    cart_chance, order_chance = funnel(category, traits, demand)
    if first:
        cart_chance, order_chance = max(cart_chance, FIRST_SESSION_CART), FIRST_SESSION_ORDER_GIVEN_CART
    if customer_id in ctx.no_order_ids:
        order_chance = 0.0  # the Offer's outcome (T18) decides whether they buy
    if rng.random() >= cart_chance:
        return events
    product = viewed[int(rng.integers(0, len(viewed)))]
    at = later(at, 10, 120)
    events.append(Event(customer_id, at, "add_to_cart", category, product.id, product.price))
    if rng.random() >= order_chance:
        abandoned_at = min(latest, at + ABANDON_AFTER)
        events.append(Event(customer_id, abandoned_at, "cart_abandoned", category, product.id, product.price))
        return events

    at = later(at, 60, 900)
    basket = ctx.catalog.categories[category].avg_basket * traits.basket_size
    amount = float(round(max(product.price, basket * rng.lognormal(-(BASKET_SIGMA**2) / 2, BASKET_SIGMA))))
    order = Event(customer_id, at, "order", category, product.id, amount)
    events.append(order)
    sim = ctx.state[customer_id]
    events.extend(expire_points(sim, customer_id, at))
    if sim.points_balance >= POINTS_BURN_MIN and rng.random() < burn_chance(traits, welcome):
        burned = min(sim.points_balance, int(amount * POINTS_BURN_MAX_SHARE / POINT_VALUE))
        sim.points_balance -= burned
        events.append(Event(customer_id, at, "points_burned", category, amount=float(burned)))
    delivered_at = at + timedelta(days=DELIVERY_DAYS)
    ctx.scheduled[delivered_at.date()].append(
        Event(customer_id, delivered_at, "delivered", category, product.id, amount)
    )
    return events


def funnel(category: str, traits: Traits, demand: float) -> tuple[float, float]:
    """(add-to-cart chance per session, order chance given a cart) in `category`. Ground Truth reuses it."""
    cart_chance = min(0.95, CART_RATE.get(category, 0.08) * traits.buy_propensity * demand)
    return cart_chance, ORDER_GIVEN_CART.get(category, 0.25)


def burn_chance(traits: Traits, welcome: bool = False) -> float:
    """Chance of burning points on an order, when the balance allows. `welcome`: in the Customer's first days."""
    chance = BURN_FLOOR + (1 - BURN_FLOOR) * traits.coupon_affinity
    return max(chance, WELCOME_BURN) if welcome else chance


def earn_points(sim: CustomerSim, delivered: Event) -> Event:
    points = int(delivered.amount * POINTS_PER_RUPEE)
    sim.points_balance += points
    sim.points_expire_at = delivered.at + POINTS_VALIDITY
    return Event(
        delivered.customer_id, delivered.at, "points_earned", delivered.category, amount=float(points)
    )


def signup_bonus(sim: CustomerSim, customer_id: str, at: datetime) -> Event:
    sim.points_balance += SIGNUP_BONUS
    sim.points_expire_at = at + POINTS_VALIDITY
    return Event(customer_id, at, "points_earned", amount=float(SIGNUP_BONUS))


def expire_points(sim: CustomerSim, customer_id: str, until: datetime) -> list[Event]:
    """Expire the whole balance if its expiry falls at or before `until`. An expiry missed on an earlier day is
    stamped at the start of `until`'s day."""
    if sim.points_expire_at is None or sim.points_expire_at > until:
        return []
    expired_at = max(sim.points_expire_at, datetime.combine(until.date(), time()))
    points = sim.points_balance
    sim.points_balance, sim.points_expire_at = 0, None
    return [Event(customer_id, expired_at, "points_expired", amount=float(points))] if points else []


def products_by_category(ctx: GenContext) -> dict[str, list[Product]]:
    grouped: dict[str, list[Product]] = {name: [] for name in ctx.catalog.categories}
    for product in sorted(ctx.catalog.products.values(), key=lambda p: p.id):
        grouped[product.category].append(product)
    return grouped


# Loyalty tier from the last 12 months' order value (₹), highest first.
LOYALTY_THRESHOLDS = (("platinum", 12_000), ("gold", 6_000), ("silver", 2_000), ("bronze", 0))


def step(ctx: GenContext) -> None:
    rng = ctx.rng("history")
    day = ctx.start
    while day < ctx.end:
        insert_events(ctx.conn, simulate_day(ctx, day, rng))
        day += timedelta(days=1)
    update_customers(ctx)
    ctx.conn.executemany(
        "UPDATE sim_customer_traits SET churned_at = ? WHERE customer_id = ?",
        [
            (sim.churned_at.isoformat(timespec="seconds") if sim.churned_at else None, cid)
            for cid, sim in ctx.state.items()
        ],
    )


def update_customers(ctx: GenContext) -> None:
    """Loyalty tier from the last year's orders, and points from `ctx.state`."""
    year_ago = (datetime.combine(ctx.end, time()) - timedelta(days=365)).isoformat()
    spend = dict(
        ctx.conn.execute(
            "SELECT customer_id, SUM(amount) FROM events WHERE kind = 'order' AND at >= ? GROUP BY customer_id",
            (year_ago,),
        ).fetchall()
    )
    rows = []
    for customer in ctx.customers:
        sim = ctx.state[customer.id]
        value = spend.get(customer.id, 0.0)
        tier = next(name for name, floor in LOYALTY_THRESHOLDS if value >= floor)
        expire = sim.points_expire_at.isoformat(timespec="seconds") if sim.points_expire_at else None
        rows.append((tier, sim.points_balance, expire, customer.id))
    ctx.conn.executemany(
        "UPDATE customers SET loyalty_tier = ?, points_balance = ?, points_expire_at = ? WHERE id = ?", rows
    )


def insert_events(conn, events: list[Event]) -> None:
    conn.executemany(
        "INSERT INTO events (customer_id, at, kind, category, product_id, amount, offer_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                e.customer_id,
                e.at.isoformat(timespec="seconds"),
                e.kind,
                e.category,
                e.product_id,
                e.amount,
                e.offer_id,
            )
            for e in events
        ],
    )
