"""Fixed Lift priors per Offer Type, used until Estimated Lift exists (T16) and for the curve's shape after.

The curve has the shape Ground Truth uses (PLAN §2.3): Lift(depth) = max Lift · (1 − e^(−depth/k)). The numbers
are guesses, not read from Ground Truth (ADR 0002).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from offer_engine.domain import OfferType


@dataclass(frozen=True)
class LiftPrior:
    max_lift: float  # added chance of buying within 7 days at saturation
    k: float  # depth at which ~63% of max Lift is reached


PRIORS = {
    OfferType.PCT_CATEGORY: LiftPrior(max_lift=0.12, k=0.10),
    OfferType.FLAT_ABOVE_MIN: LiftPrior(max_lift=0.10, k=0.10),
    OfferType.FREE_SHIPPING: LiftPrior(max_lift=0.04, k=0.50),
    OfferType.POINTS_MULTIPLIER: LiftPrior(max_lift=0.05, k=1.00),
    OfferType.NUDGE: LiftPrior(max_lift=0.02, k=0.50),
}

# Chance a Customer buys within 7 days without an Offer.
BASE_BUY_CHANCE = 0.10


def offer_depth(offer_type: OfferType, params: dict[str, float], basket: float) -> float:
    """How deep an Offer is, as Ground Truth measures it: pct/100, flat amount ÷ expected basket, 1 for free
    shipping and a Nudge, multiplier − 1 for points.
    """
    if offer_type == OfferType.PCT_CATEGORY:
        return params["pct"] / 100
    if offer_type == OfferType.FLAT_ABOVE_MIN:
        return params["amount"] / basket if basket > 0 else 0.0
    if offer_type == OfferType.POINTS_MULTIPLIER:
        return params["multiplier"] - 1
    return 1.0


def lift_at(offer_type: OfferType, depth: float, estimated_lift: float | None = None) -> float:
    """Lift at `depth`. An Estimated Lift replaces the prior's max Lift; the prior keeps the curve's shape."""
    prior = PRIORS[offer_type]
    max_lift = prior.max_lift if estimated_lift is None else estimated_lift
    return max_lift * (1 - math.exp(-depth / prior.k))
