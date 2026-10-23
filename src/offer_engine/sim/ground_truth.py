"""Ground Truth (ADR 0002): each Customer's hidden response formula per Offer Type and the Response Class derived
from it. Only the simulator reads it; the decision pipeline never does.

`base` is the Customer's organic chance of ordering within 7 days: the history funnel at normal demand (no season),
so the live world and Ground Truth agree. Lift parameters come from the traits behind observable behaviour, plus
noise: points burners (`coupon_affinity`) respond to discounts and points, small baskets and tier-2/3 cities to
free shipping, and a Nudge lifts a little. Sleeping Dogs buy less with any Offer.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from offer_engine.domain import Category, OfferType

if TYPE_CHECKING:
    from offer_engine.sim.generate import GenContext
    from offer_engine.sim.generate.customers import Traits

RESPONSE_CLASSES = ("lost_cause", "sure_thing", "persuadable", "sleeping_dog")

# Response Class is judged on a typical Offer: 15% off (depth doesn't depend on the category).
TYPICAL_PCT = 15.0
# Thresholds, checked in this order on the typical Offer's Lift and the base chance. The rest are Lost Causes.
SLEEPING_DOG_LIFT = 0.0  # Lift below this
SURE_THING_BASE = 0.08  # base at or above this
PERSUADABLE_LIFT = 0.05  # Lift at or above this

# Calibration target 9 (docs/research/ecommerce-benchmarks.md) as shares of all Customers.
TARGET_SHARES = {
    "lost_cause": (0.70, 0.85),
    "sure_thing": (0.05, 0.15),
    "persuadable": (0.03, 0.10),
    "sleeping_dog": (0.01, 0.05),
}

SLEEPING_DOG_CHANCE = 0.03
SLEEPING_DOG_DROP = (0.3, 0.8)  # a Sleeping Dog's max Lift is −base × U(lo, hi) for every Offer Type

# Mean max Lift before noise. Discounts: DISCOUNT_LIFT × coupon_affinity². Free shipping: FREE_SHIPPING_LIFT ×
# basket_size^−1.5 × the city tier factor.
DISCOUNT_LIFT = 0.13
POINTS_LIFT_SHARE = 0.4  # points multiplier max Lift as a share of the discount one
FREE_SHIPPING_LIFT = 0.012
FREE_SHIPPING_BY_CITY_TIER = {1: 0.6, 2: 1.0, 3: 1.5}
NUDGE_LIFT = 0.008
LIFT_NOISE_SIGMA = 0.5

# Saturation depth per Offer Type, in that type's depth units; each Customer's k varies around it.
K = {
    OfferType.PCT_CATEGORY: 0.12,
    OfferType.FLAT_ABOVE_MIN: 0.12,
    OfferType.FREE_SHIPPING: 0.5,
    OfferType.NUDGE: 0.5,
    OfferType.POINTS_MULTIPLIER: 1.0,
}
K_NOISE_SIGMA = 0.2


@dataclass(frozen=True)
class GroundTruth:
    customer_id: str
    offer_type: OfferType
    base: float
    max_lift: float
    k: float


def p_buy(gt: GroundTruth, depth: float) -> float:
    """Chance of buying within 7 days given an Offer of `depth` (0 = no Offer)."""
    return min(1.0, max(0.0, gt.base + gt.max_lift * (1 - math.exp(-depth / gt.k))))


def offer_depth(offer_type: OfferType, params: dict[str, float], catalog_category: Category | None) -> float:
    """How strong an Offer is, in its type's units. `flat_above_min` needs the category whose basket it applies to."""
    if offer_type == OfferType.PCT_CATEGORY:
        return params["pct"] / 100
    if offer_type == OfferType.FLAT_ABOVE_MIN:
        if catalog_category is None:
            raise ValueError("flat_above_min depth needs a category's average basket")
        return params["amount"] / catalog_category.avg_basket
    if offer_type == OfferType.POINTS_MULTIPLIER:
        return params["multiplier"] - 1
    return 1.0


def response_class(gts: list[GroundTruth]) -> str:
    """Response Class from the `pct_category` formula at the typical Offer."""
    gt = next(g for g in gts if g.offer_type == OfferType.PCT_CATEGORY)
    lift = p_buy(gt, TYPICAL_PCT / 100) - gt.base
    if lift < SLEEPING_DOG_LIFT:
        return "sleeping_dog"
    if gt.base >= SURE_THING_BASE:
        return "sure_thing"
    if lift >= PERSUADABLE_LIFT:
        return "persuadable"
    return "lost_cause"


def organic_weekly_chance(traits: Traits, lapsed: bool) -> float:
    """Chance of at least one order in 7 days with no Offer. Sessions are Poisson, so orders are too."""
    from offer_engine.sim.generate.history import LAPSED_VISIT_FACTOR, funnel

    per_session = 0.0
    for category, share in traits.category_affinity.items():
        cart_chance, order_chance = funnel(category, traits, demand=1.0)
        per_session += share * cart_chance * order_chance
    sessions = 7 * traits.visit_rate * (LAPSED_VISIT_FACTOR if lapsed else 1.0)
    return 1 - math.exp(-sessions * per_session)


def draw(
    rng: np.random.Generator, customer_id: str, traits: Traits, city_tier: int, lapsed: bool
) -> dict[OfferType, GroundTruth]:
    from offer_engine.sim.generate.customers import mean_one_lognormal

    base = organic_weekly_chance(traits, lapsed)
    sleeping_dog = rng.random() < SLEEPING_DOG_CHANCE
    drop = rng.uniform(*SLEEPING_DOG_DROP)
    discount = DISCOUNT_LIFT * traits.coupon_affinity**2
    mean_lift = {
        OfferType.PCT_CATEGORY: discount,
        OfferType.FLAT_ABOVE_MIN: discount,
        OfferType.POINTS_MULTIPLIER: POINTS_LIFT_SHARE * discount,
        OfferType.FREE_SHIPPING: FREE_SHIPPING_LIFT
        * traits.basket_size**-1.5
        * FREE_SHIPPING_BY_CITY_TIER[city_tier],
        OfferType.NUDGE: NUDGE_LIFT,
    }
    gts = {}
    for offer_type in OfferType:
        noise = mean_one_lognormal(rng, LIFT_NOISE_SIGMA)
        k = K[offer_type] * float(rng.lognormal(0, K_NOISE_SIGMA))
        max_lift = -base * drop if sleeping_dog else mean_lift[offer_type] * noise
        gts[offer_type] = GroundTruth(customer_id, offer_type, base, float(max_lift), k)
    return gts


def load(conn: sqlite3.Connection, customer_id: str) -> dict[OfferType, GroundTruth]:
    rows = conn.execute("SELECT * FROM sim_ground_truth WHERE customer_id = ?", (customer_id,))
    return {gt.offer_type: gt for gt in map(_from_row, rows)}


def load_all(conn: sqlite3.Connection) -> dict[str, dict[OfferType, GroundTruth]]:
    out: dict[str, dict[OfferType, GroundTruth]] = {}
    for gt in map(_from_row, conn.execute("SELECT * FROM sim_ground_truth ORDER BY customer_id")):
        out.setdefault(gt.customer_id, {})[gt.offer_type] = gt
    return out


def _from_row(row: sqlite3.Row) -> GroundTruth:
    return GroundTruth(
        row["customer_id"], OfferType(row["offer_type"]), row["base"], row["max_lift"], row["k"]
    )


def step(ctx: GenContext) -> None:
    """Draw Ground Truth for every Customer from their traits and lapse state at the end of history."""
    rng = ctx.rng("ground_truth")
    gt_rows, class_rows = [], []
    for customer in ctx.customers:
        lapsed = ctx.state[customer.id].churned_at is not None
        gts = draw(rng, customer.id, ctx.traits[customer.id], customer.city_tier, lapsed)
        gt_rows += [(g.customer_id, str(g.offer_type), g.base, g.max_lift, g.k) for g in gts.values()]
        class_rows.append((customer.id, response_class(list(gts.values()))))
    ctx.conn.executemany(
        "INSERT INTO sim_ground_truth (customer_id, offer_type, base, max_lift, k) VALUES (?, ?, ?, ?, ?)",
        gt_rows,
    )
    ctx.conn.executemany(
        "INSERT INTO sim_response_class (customer_id, response_class) VALUES (?, ?)", class_rows
    )
