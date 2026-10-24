"""What the offline Policy runs are scored on (PLAN §5, QnA Q31).

Headline: Incremental Margin per ₹ of offer spend. Incremental Margin is the margin net of Offer costs under the
Policy minus the margin under No Offers, over the same Customers, days and seed. Supporting: Offers sent, Claimed
and Redeemed; spend on Sure Things; Validation rejections and Fallbacks; lift by decile (Estimated Lift against
Ground Truth Lift, in deciles of Estimated Lift).
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass

from offer_engine.sim.offline import OfferRecord, PolicyResult

DECILES = 10


@dataclass(frozen=True)
class Decile:
    decile: int  # 1 = lowest Estimated Lift
    offers: int
    estimated_lift: float
    true_lift: float


@dataclass(frozen=True)
class PolicyMetrics:
    policy: str
    scope: str  # "population" or "sample"
    customers: int
    offers_sent: int
    claimed: int
    redeemed: int
    spend: float
    incremental_margin: float
    per_rupee: float | None  # None with no spend
    sure_thing_spend: float
    validation_rejections: int
    fallbacks: int
    lift_deciles: tuple[Decile, ...]
    runtime_seconds: float


def incremental_margin(result: PolicyResult, baseline: PolicyResult, customers: Iterable[str]) -> float:
    if (result.start, result.days, result.seed) != (baseline.start, baseline.days, baseline.seed):
        raise ValueError("the baseline must share the run's start, days and seed")
    return sum(result.margin.get(c, 0.0) - baseline.margin.get(c, 0.0) for c in customers)


def spend(offers: Iterable[OfferRecord], sure_things_only: bool = False) -> float:
    return sum(o.cost for o in offers if o.redeemed and (o.sure_thing or not sure_things_only))


def lift_deciles(offers: Iterable[OfferRecord], n: int = DECILES) -> tuple[Decile, ...]:
    """Sent Offers with both lifts, in `n` equal groups by Estimated Lift (fewer if there are fewer Offers)."""
    graded = sorted(
        (o.estimated_lift, o.true_lift)
        for o in offers
        if o.sent and o.estimated_lift is not None and o.true_lift is not None
    )
    groups = min(n, len(graded))
    out = []
    for i in range(groups):
        chunk = graded[i * len(graded) // groups : (i + 1) * len(graded) // groups]
        out.append(
            Decile(
                i + 1,
                len(chunk),
                sum(e for e, _ in chunk) / len(chunk),
                sum(t for _, t in chunk) / len(chunk),
            )
        )
    return tuple(out)


def summarise(
    result: PolicyResult, baseline: PolicyResult, customers: Collection[str], scope: str
) -> PolicyMetrics:
    """`result` scored on `customers` against the No Offers `baseline`."""
    members = set(customers)
    offers = [o for o in result.offers if o.customer_id in members]
    total = spend(offers)
    gain = incremental_margin(result, baseline, members)
    return PolicyMetrics(
        policy=result.policy,
        scope=scope,
        customers=len(members),
        offers_sent=sum(o.sent for o in offers),
        claimed=sum(o.claimed for o in offers),
        redeemed=sum(o.redeemed for o in offers),
        spend=total,
        incremental_margin=gain,
        per_rupee=gain / total if total > 0 else None,
        sure_thing_spend=spend(offers, sure_things_only=True),
        validation_rejections=sum(n for c, n in result.rejections.items() if c in members),
        fallbacks=sum(n for c, n in result.fallbacks.items() if c in members),
        lift_deciles=lift_deciles(offers),
        runtime_seconds=result.runtime_seconds,
    )
