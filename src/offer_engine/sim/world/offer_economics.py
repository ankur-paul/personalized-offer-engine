"""What a Redemption's order looks like: its basket, the Offer's discount on it and the margin left (PLAN §4.3).
Past Offers (T14) and the live world (T18) draw baskets the same way, as organic orders do."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from offer_engine.budget import redemption_cost
from offer_engine.domain import Category, OfferType, Product, RuleSet
from offer_engine.sim.generate.history import BASKET_SIGMA


@dataclass(frozen=True)
class RedemptionOrder:
    basket: float  # ₹ before the discount, as the `order` event records it
    discount: float  # what the Offer cost, as the `offer_redeemed` event records it
    margin: float  # the basket's margin minus the discount


def draw_basket(rng: np.random.Generator, mean_basket: float, price: float, min_basket: float = 0.0) -> float:
    """A basket around `mean_basket` (lognormal, mean one), at least the product's price and the Offer's minimum."""
    basket = max(price, mean_basket * rng.lognormal(-(BASKET_SIGMA**2) / 2, BASKET_SIGMA))
    return float(round(max(basket, min_basket)))


def redemption_order(
    offer_type: OfferType,
    params: dict[str, float],
    category: Category,
    product: Product,
    rng: np.random.Generator,
    basket_size: float = 1.0,
    rules: RuleSet | None = None,
) -> RedemptionOrder:
    """The order an Offer is redeemed on: a basket in `category` scaled by the Customer's `basket_size`."""
    basket = draw_basket(rng, category.avg_basket * basket_size, product.price, params.get("min_basket", 0.0))
    discount = redemption_cost(offer_type, params, basket, rules or RuleSet())
    return RedemptionOrder(basket, discount, basket * category.margin_pct / 100 - discount)
