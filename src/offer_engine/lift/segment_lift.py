"""Estimated Lift v1 (PLAN §3.4, "Assumed › Deciding"): per segment and Offer Type, from the history's random past
Offers. Reads only `customers`, `events`, `offers` and `categories`.

A segment is loyalty tier × days since the last order (≤30, 31–90, >90 or never) × coupon user (redeemed at least 2
past Offers). Lift is the share who bought within 7 days of a past Offer's send minus the share who bought within 7
days of a comparable no-offer moment in the same segment. The moments are found in `events` the way T14 chose
them: each abandoned cart, every 45 days without an order and the weekly Friday 18:00 broadcast slot. A moment
inside a past Offer's 7 days, after the Customer opted out, or whose 7 days run past the history doesn't count.
Holdout Customers are left out, as T14 left them out: they never had a past Offer to redeem, so they would all
count as non-coupon users and skew those segments' no-offer rate.

The choosers read Estimated Lift as max Lift, the Lift at full depth (`priors.lift_at`). Past Offers had random
depths, so the observed Lift is divided by their mean saturation on the prior's curve. A segment with fewer than 30
past Offers of a type takes that type's average over every segment.
"""

from __future__ import annotations

import bisect
import itertools
import json
import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from offer_engine import clock
from offer_engine.choosers.priors import PRIORS, offer_depth
from offer_engine.domain import CustomerState, EligibleOption, OfferSource, OfferType, RuleSet
from offer_engine.rules import in_holdout

Segment = tuple[str, str, bool]  # (loyalty tier, recency bucket, coupon user)

MIN_PAST_OFFERS = 30
COUPON_USER_REDEMPTIONS = 2
RECENCY_BUCKETS = ((timedelta(days=30), "<=30"), (timedelta(days=90), "31-90"))
NO_RECENT_ORDER = ">90"
HORIZON = timedelta(days=7)  # Ground Truth's horizon; a past Offer decides the Customer's buying for 7 days

# The history was generated under the default Rules (T14).
HISTORY_RULES = RuleSet()
BROADCAST_WEEKDAY, BROADCAST_HOUR = 4, 18


def segment_of(state: CustomerState, now: datetime) -> Segment:
    orders = sorted(e.at for e in state.events if e.kind == "order")
    redemptions = sorted(o.redeemed_at for o in state.offers if o.redeemed_at is not None)
    return _segment(state.customer.loyalty_tier, orders, redemptions, now)


def _segment(tier: str, orders: list[datetime], redemptions: list[datetime], at: datetime) -> Segment:
    """`orders` and `redemptions` are sorted; only those at or before `at` count."""
    i = bisect.bisect_right(orders, at)
    recency = NO_RECENT_ORDER
    if i:
        gap = at - orders[i - 1]
        recency = next((label for limit, label in RECENCY_BUCKETS if gap <= limit), NO_RECENT_ORDER)
    return tier, recency, bisect.bisect_right(redemptions, at) >= COUPON_USER_REDEMPTIONS


@dataclass(frozen=True)
class SegmentLift:
    """The last fit's Estimated Lift, for Decisions at `now`."""

    by_segment: dict[tuple[Segment, OfferType], float]
    by_type: dict[OfferType, float]
    now: datetime

    def estimate(self, state: CustomerState, option: EligibleOption) -> float | None:
        """The segment's Estimated Lift for the option's Offer Type, else the type average, else None."""
        key = (segment_of(state, self.now), option.offer_type)
        return self.by_segment.get(key, self.by_type.get(option.offer_type))


def load(conn: sqlite3.Connection, now: datetime) -> SegmentLift | None:
    """None until `offer-engine lift fit` has written `lift_estimates`."""
    by_segment, by_type = {}, {}
    query = "SELECT offer_type, loyalty_tier, recency, coupon_user, estimated_lift FROM lift_estimates"
    for offer_type, tier, recency, coupon_user, lift in conn.execute(query):
        if tier is None:
            by_type[OfferType(offer_type)] = lift
        else:
            by_segment[((tier, recency, bool(coupon_user)), OfferType(offer_type))] = lift
    if not by_segment and not by_type:
        return None
    return SegmentLift(by_segment, by_type, now)


# --- Fitting -----------------------------------------------------------------------------------


@dataclass
class Tally:
    offers: int = 0
    offer_buys: int = 0
    saturation: float = 0.0  # summed over the past Offers: the share of max Lift each Offer's depth reaches
    moments: int = 0
    moment_buys: int = 0

    def add(self, other: Tally) -> None:
        self.offers += other.offers
        self.offer_buys += other.offer_buys
        self.saturation += other.saturation
        self.moments += other.moments
        self.moment_buys += other.moment_buys

    @property
    def observed_lift(self) -> float | None:
        if not self.offers or not self.moments:
            return None
        return self.offer_buys / self.offers - self.moment_buys / self.moments

    @property
    def max_lift(self) -> float | None:
        observed = self.observed_lift
        return None if observed is None else observed / (self.saturation / self.offers)


def fit(conn: sqlite3.Connection) -> int:
    """Rewrite `lift_estimates` from the history, stamped with the clock's time. Returns the rows written."""
    offer_tallies, moment_tallies = tally(conn)
    by_type: dict[OfferType, Tally] = defaultdict(Tally)
    for (_, offer_type), t in offer_tallies.items():
        by_type[offer_type].add(t)
    all_moments = Tally()
    for m in moment_tallies.values():
        all_moments.add(m)
    for t in by_type.values():
        t.add(all_moments)

    fitted_at = clock.now(conn).isoformat(timespec="seconds")
    rows = []
    for offer_type, total in sorted(by_type.items()):
        average = total.max_lift
        if average is None:
            continue
        rows.append((offer_type, None, None, None, total, average, False))
        for segment in sorted(set(moment_tallies) | {s for s, _ in offer_tallies}):
            t = Tally()
            t.add(offer_tallies.get((segment, offer_type), Tally()))
            t.add(moment_tallies.get(segment, Tally()))
            own = t.max_lift if t.offers >= MIN_PAST_OFFERS else None
            rows.append((offer_type, *segment, t, average if own is None else own, own is None))
    with conn:
        conn.execute("DELETE FROM lift_estimates")
        conn.executemany(
            "INSERT INTO lift_estimates (offer_type, loyalty_tier, recency, coupon_user, past_offers, moments,"
            " offer_rate, base_rate, observed_lift, estimated_lift, from_type_avg, fitted_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    str(offer_type),
                    tier,
                    recency,
                    None if coupon_user is None else int(coupon_user),
                    t.offers,
                    t.moments,
                    t.offer_buys / t.offers if t.offers else None,
                    t.moment_buys / t.moments if t.moments else None,
                    t.observed_lift,
                    lift,
                    int(from_type_avg),
                    fitted_at,
                )
                for offer_type, tier, recency, coupon_user, t, lift, from_type_avg in rows
            ],
        )
    return len(rows)


@dataclass(frozen=True)
class HistoryOffer:
    created_at: datetime
    send_at: datetime
    offer_type: OfferType
    saturation: float


def tally(
    conn: sqlite3.Connection,
) -> tuple[dict[tuple[Segment, OfferType], Tally], dict[Segment, Tally]]:
    """Past Offers and their buys by segment and Offer Type; no-offer moments and their buys by segment."""
    first = conn.execute("SELECT MIN(at) FROM events").fetchone()[0]
    if first is None:
        return {}, {}
    start, end = datetime.fromisoformat(first).date(), clock.START
    events = _events(conn, end)
    redemptions = _redemptions(conn)
    past = _past_offers(conn, end)
    broadcasts = _broadcast_slots(start, end)

    offer_tallies: dict[tuple[Segment, OfferType], Tally] = defaultdict(Tally)
    moment_tallies: dict[Segment, Tally] = defaultdict(Tally)
    for cid, signup, tier in conn.execute(
        "SELECT id, signup_at, loyalty_tier FROM customers WHERE is_tester_copy = 0"
    ):
        if in_holdout(cid, HISTORY_RULES.holdout_pct):
            continue
        signup = datetime.fromisoformat(signup)
        orders = events[cid]["order"]
        mine = past.get(cid, [])
        for o in mine:
            t = offer_tallies[(_segment(tier, orders, redemptions[cid], o.created_at), o.offer_type)]
            t.offers += 1
            t.offer_buys += _bought(orders, o.send_at)
            t.saturation += o.saturation

        opted_out = min(events[cid]["opted_out"], default=None)
        moments = events[cid]["cart_abandoned"] + _long_gaps(signup, orders, start, end)
        moments += [at for at in broadcasts if at > signup]
        for at in moments:
            send_at = _send_time(at)
            if send_at + HORIZON > end or (opted_out is not None and at >= opted_out):
                continue
            if any(o.created_at <= at < o.send_at + HORIZON for o in mine):
                continue
            t = moment_tallies[_segment(tier, orders, redemptions[cid], at)]
            t.moments += 1
            t.moment_buys += _bought(orders, send_at)
    return dict(offer_tallies), dict(moment_tallies)


def _events(conn: sqlite3.Connection, end: datetime) -> dict[str, dict[str, list[datetime]]]:
    out: dict[str, dict[str, list[datetime]]] = defaultdict(lambda: defaultdict(list))
    query = (
        "SELECT customer_id, kind, at FROM events WHERE kind IN ('order', 'cart_abandoned', 'opted_out')"
        " AND at < ? ORDER BY at"
    )
    for cid, kind, at in conn.execute(query, (end.isoformat(timespec="seconds"),)):
        out[cid][kind].append(datetime.fromisoformat(at))
    return out


def _redemptions(conn: sqlite3.Connection) -> dict[str, list[datetime]]:
    out: dict[str, list[datetime]] = defaultdict(list)
    query = "SELECT customer_id, redeemed_at FROM offers WHERE redeemed_at IS NOT NULL ORDER BY redeemed_at"
    for cid, at in conn.execute(query):
        out[cid].append(datetime.fromisoformat(at))
    return out


def _past_offers(conn: sqlite3.Connection, end: datetime) -> dict[str, list[HistoryOffer]]:
    """The history's random past Offers whose 7 days after the send end inside the history, by Customer."""
    baskets = [row[0] for row in conn.execute("SELECT avg_basket FROM categories")]
    basket = sum(baskets) / len(baskets) if baskets else 0.0
    out: dict[str, list[HistoryOffer]] = defaultdict(list)
    query = (
        "SELECT customer_id, offer_type, params, created_at, send_at FROM offers WHERE source = ?"
        " ORDER BY created_at, id"
    )
    for cid, offer_type, params, created_at, send_at in conn.execute(query, (OfferSource.HISTORY_RANDOM,)):
        send_at = datetime.fromisoformat(send_at)
        if send_at + HORIZON > end:
            continue
        offer_type = OfferType(offer_type)
        depth = offer_depth(offer_type, json.loads(params), basket)
        saturation = 1 - math.exp(-depth / PRIORS[offer_type].k)
        out[cid].append(HistoryOffer(datetime.fromisoformat(created_at), send_at, offer_type, saturation))
    return out


def _bought(orders: list[datetime], start: datetime) -> bool:
    i = bisect.bisect_left(orders, start)
    return i < len(orders) and orders[i] < start + HORIZON


def _long_gaps(signup_at: datetime, orders: list[datetime], start: date, end: datetime) -> list[datetime]:
    """Every 45 days without an order, counted from signup and from each order, inside the history."""
    window_start = datetime.combine(start, time())
    step = timedelta(days=HISTORY_RULES.long_gap_days)
    out = []
    for since, until in itertools.pairwise([signup_at, *orders, end]):
        at = since + max(1, math.ceil((window_start - since) / step)) * step
        while at < until:
            out.append(at)
            at += step
    return out


def _broadcast_slots(start: date, end: datetime) -> list[datetime]:
    day = start + timedelta(days=(BROADCAST_WEEKDAY - start.weekday()) % 7)
    out = []
    while (at := datetime.combine(day, time(BROADCAST_HOUR))) < end:
        out.append(at)
        day += timedelta(days=7)
    return out


def _send_time(at: datetime) -> datetime:
    """`at` if inside the history's send hours, else the next opening."""
    opening = at.replace(hour=HISTORY_RULES.send_hour_start, minute=0, second=0, microsecond=0)
    if at.hour < HISTORY_RULES.send_hour_start:
        return opening
    if at.hour >= HISTORY_RULES.send_hour_end:
        return opening + timedelta(days=1)
    return at
