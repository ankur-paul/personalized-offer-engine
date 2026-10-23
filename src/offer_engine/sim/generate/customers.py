"""Customers step: observable profiles in `customers`, hidden behaviour traits in `sim_customer_traits`.

IDs run `C00001…` in signup order. Loyalty tier and points are placeholders here; the history step sets them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING

import numpy as np

from offer_engine.domain import Customer

if TYPE_CHECKING:
    from offer_engine.sim.generate import GenContext

IN_WINDOW_SHARE = (
    0.45  # Customers who sign up during the history window; the rest signed up up to 2 years before
)
PRE_WINDOW_DAYS = 730
PRE_WINDOW_LAPSED = 0.45  # chance an older Customer had already lapsed when the window opens

CITY_TIERS = ((1, 2, 3), (0.40, 0.35, 0.25))
DEVICES = (("android", "ios", "web"), (0.72, 0.12, 0.16))
CHANNELS = (("organic", "paid_search", "social", "referral", "affiliate"), (0.35, 0.20, 0.20, 0.15, 0.10))

# Dirichlet weights for the share of sessions per category. Grocery regulars put most sessions into grocery.
AFFINITY_ALPHA = {"grocery": 0.3, "electronics": 0.5, "fashion": 1.2, "beauty": 0.8, "home": 0.6}
GROCERY_REGULAR_ALPHA = 6.0
GROCERY_REGULAR_SHARE = {1: 0.35, 2: 0.25, 3: 0.12}
GROCERY_REGULAR_VISITS = 3.0  # grocery regulars open the app more often
BASKET_BY_CITY_TIER = {1: 1.15, 2: 1.0, 3: 0.85}

VISIT_RATE_MEDIAN = 0.32  # sessions per day
VISIT_RATE_SIGMA = 1.0
BUY_PROPENSITY_SIGMA = 0.8
BASKET_SIGMA = 0.35
CHURN_HAZARD_MEDIAN = 0.0004
CHURN_HAZARD_SIGMA = 0.6

PRE_WINDOW_NO_POINTS = 0.35
PRE_WINDOW_POINTS_MEDIAN = 150


@dataclass(frozen=True)
class Traits:
    visit_rate: float
    buy_propensity: float
    basket_size: float
    category_affinity: dict[str, float]
    coupon_affinity: float
    churn_hazard: float


def mean_one_lognormal(rng: np.random.Generator, sigma: float) -> float:
    return float(rng.lognormal(-(sigma**2) / 2, sigma))


def random_time_between(rng: np.random.Generator, lo: datetime, hi: datetime) -> datetime:
    seconds = int((hi - lo).total_seconds())
    return lo + timedelta(seconds=int(rng.integers(0, seconds)))


def draw_traits(rng: np.random.Generator, categories: list[str], city_tier: int) -> Traits:
    alpha = np.array([AFFINITY_ALPHA.get(c, 1.0) for c in categories])
    visits = VISIT_RATE_MEDIAN * rng.lognormal(0, VISIT_RATE_SIGMA)
    if "grocery" in categories and rng.random() < GROCERY_REGULAR_SHARE[city_tier]:
        alpha[categories.index("grocery")] = GROCERY_REGULAR_ALPHA
        visits *= GROCERY_REGULAR_VISITS
    affinity = rng.dirichlet(alpha)
    return Traits(
        visit_rate=float(visits),
        buy_propensity=mean_one_lognormal(rng, BUY_PROPENSITY_SIGMA),
        basket_size=mean_one_lognormal(rng, BASKET_SIGMA) * BASKET_BY_CITY_TIER[city_tier],
        category_affinity={c: round(float(a), 4) for c, a in zip(categories, affinity)},
        coupon_affinity=float(rng.beta(0.7, 1.6)),
        churn_hazard=float(CHURN_HAZARD_MEDIAN * rng.lognormal(0, CHURN_HAZARD_SIGMA)),
    )


def step(ctx: GenContext) -> None:
    from offer_engine.sim.generate import CustomerSim

    rng = ctx.rng("customers")
    window_start = datetime.combine(ctx.start, time())
    window_end = datetime.combine(ctx.end, time())
    pre_start = window_start - timedelta(days=PRE_WINDOW_DAYS)
    signups = sorted(
        random_time_between(rng, window_start, window_end)
        if rng.random() < IN_WINDOW_SHARE
        else random_time_between(rng, pre_start, window_start)
        for _ in range(ctx.n_customers)
    )
    categories = list(ctx.catalog.categories)
    for number, signup_at in enumerate(signups, start=1):
        city_tier = int(rng.choice(CITY_TIERS[0], p=CITY_TIERS[1]))
        customer = Customer(
            id=f"C{number:05d}",
            signup_at=signup_at,
            city_tier=city_tier,
            device=str(rng.choice(DEVICES[0], p=DEVICES[1])),
            channel=str(rng.choice(CHANNELS[0], p=CHANNELS[1])),
            loyalty_tier="bronze",
            points_balance=0,
            points_expire_at=None,
        )
        ctx.customers.append(customer)
        ctx.traits[customer.id] = draw_traits(rng, categories, city_tier)
        sim = CustomerSim()
        if signup_at < window_start:
            if rng.random() < PRE_WINDOW_LAPSED:
                sim.churned_at = random_time_between(rng, signup_at, window_start)
            if rng.random() >= PRE_WINDOW_NO_POINTS:
                sim.points_balance = int(PRE_WINDOW_POINTS_MEDIAN * rng.lognormal(0, 0.8))
                sim.points_expire_at = window_start + timedelta(days=float(rng.uniform(1, 180)))
        ctx.state[customer.id] = sim

    ctx.conn.executemany(
        "INSERT INTO customers (id, signup_at, city_tier, device, channel, loyalty_tier) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                c.id,
                c.signup_at.isoformat(timespec="seconds"),
                c.city_tier,
                c.device,
                c.channel,
                c.loyalty_tier,
            )
            for c in ctx.customers
        ],
    )
    ctx.conn.executemany(
        "INSERT INTO sim_customer_traits (customer_id, visit_rate, buy_propensity, basket_size, category_affinity,"
        " coupon_affinity, churn_hazard) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                cid,
                t.visit_rate,
                t.buy_propensity,
                t.basket_size,
                json.dumps(t.category_affinity),
                t.coupon_affinity,
                t.churn_hazard,
            )
            for cid, t in ctx.traits.items()
        ],
    )
