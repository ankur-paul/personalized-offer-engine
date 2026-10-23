"""Past Offers step (PLAN §2.2): Offers sent partly at random through the history, as A/B tests would be, with
Claims and Redemptions settled by Ground Truth, so Estimated Lift (T16) can be learned from `offers` and `events`.

Moments are each abandoned cart, each 45 days without an order and a weekly broadcast slot. At each one, a Customer
outside the Holdout who hasn't opted out gets an Offer with chance 0.3, its Offer Type and depth drawn at random.
Only moments whose 7 days after the send end inside the history count, so every past Offer is settled, and a
Customer has one past Offer at a time: moments inside an earlier Offer's 7 days aren't drawn. Overlapping Offers
would each draw a purchase, so a Customer would buy more often than any Offer's `p_buy` says.

An Offer decides whether the Customer buys in the 7 days after the send, Ground Truth's horizon (docs/QnA.md Q39).
With chance `p_buy` they buy inside the validity window, which is the Redemption; organic orders between the send
and the Redemption are removed, and later ones stay. Otherwise every organic order in the 7 days is removed. Each
removed order takes everything that followed it. `p_buy` uses the base at the moment (Q40). Points are
then replayed for the Customers whose orders changed, so balances and expiries match the new orders.

A redemption `order` carries the basket before discount and the Offer's id; its `offer_redeemed` event carries the
Offer's cost in ₹. Every moment goes to `sim_history_moments` with its chance of buying, for tests only.
"""

from __future__ import annotations

import itertools
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from functools import partial
from typing import TYPE_CHECKING

import numpy as np

from offer_engine.budget import redemption_cost
from offer_engine.choosers.priors import BASE_BUY_CHANCE, lift_at
from offer_engine.choosers.rules_chooser import CAP_STEP
from offer_engine.domain import Event, OfferSource, OfferStatus, OfferType, RuleSet
from offer_engine.pipeline import CODE_ALPHABET, CODE_PREFIX
from offer_engine.rules import MIN_CAP, in_holdout, offer_cost
from offer_engine.sim import ground_truth
from offer_engine.sim.generate.history import (
    BASKET_SIGMA,
    DELIVERY_DAYS,
    POINT_VALUE,
    POINTS_BURN_MAX_SHARE,
    POINTS_BURN_MIN,
    POINTS_PER_RUPEE,
    POINTS_VALIDITY,
    RETURN_DAYS,
    RETURN_RATE,
    insert_events,
    products_by_category,
    season,
    update_customers,
)

if TYPE_CHECKING:
    from offer_engine.domain import Product
    from offer_engine.sim.generate import CustomerSim, GenContext

EVENT_KINDS = ("offer_claimed", "offer_dismissed", "offer_redeemed", "opted_out")

RULES = RuleSet()
SEND_CHANCE = 0.3
PCT_RANGE = (5, 30)
FLAT_RANGE = (100, 500)  # ₹, in steps of 10
POINTS_RANGE = (1.5, 3.0)
HORIZON = timedelta(days=7)  # Ground Truth's p_buy is a 7-day chance
LONG_GAP = timedelta(days=RULES.long_gap_days)
BROADCAST_WEEKDAY, BROADCAST_HOUR = 4, 18  # Friday 18:00

CLAIM_WITHOUT_BUYING = 0.25
DISMISS_CHANCE = 0.05
# Calibration target 12: Telegram opt-out is 0.5–1.5% per message. Past Offers are at most one a week, so the
# assumed doubling above 2 messages a week never applies.
OPT_OUT_CHANCE = 0.005

TRIGGERS = ("cart_abandoned", "long_gap", "broadcast")
TARGETED = ("cart_abandoned", "long_gap")


@dataclass(frozen=True)
class Moment:
    at: datetime
    trigger: str
    category: str


@dataclass
class Ledger:
    """The organic history's orders and what followed them, by Customer, loaded before any change."""

    orders: dict[str, list[tuple]] = field(
        default_factory=lambda: defaultdict(list)
    )  # (id, at, cat, product, ₹)
    follow_ons: dict[tuple, list[tuple]] = field(
        default_factory=lambda: defaultdict(list)
    )  # key -> [(id, at)]
    points: dict[str, list[tuple]] = field(
        default_factory=lambda: defaultdict(list)
    )  # (id, at, kind, cat, n)
    start_points: dict[str, tuple[int, datetime | None]] = field(default_factory=dict)


def step(ctx: GenContext) -> None:
    rng = ctx.rng("past_offers")
    gts = ground_truth.load_all(ctx.conn)
    ledger = _load(ctx)
    carts = defaultdict(list)
    query = "SELECT customer_id, at, category FROM events WHERE kind = 'cart_abandoned' ORDER BY id"
    for cid, at, category in ctx.conn.execute(query):
        carts[cid].append(Moment(datetime.fromisoformat(at), "cart_abandoned", category))
    by_category = products_by_category(ctx)
    end = datetime.combine(ctx.end, time())
    broadcasts = _broadcast_slots(ctx.start, ctx.end)
    codes: set[str] = set()

    offers, moments, new_events, removed, opted_out = [], [], [], [], []
    for customer in ctx.customers:
        if in_holdout(customer.id, RULES.holdout_pct):
            continue
        traits = ctx.traits[customer.id]
        orders = ledger.orders[customer.id]
        top = max(traits.category_affinity, key=traits.category_affinity.get)
        found = carts[customer.id] + _long_gaps(
            customer.signup_at, [o[1] for o in orders], ctx.start, end, top
        )
        found += [Moment(at, "broadcast", top) for at in broadcasts if at > customer.signup_at]
        found.sort(key=lambda m: (m.at, TRIGGERS.index(m.trigger)))

        churned_at = ctx.state[customer.id].churned_at
        bases: dict[tuple[bool, date], float] = {}
        sends: list[datetime] = []
        spans: list[tuple[datetime, datetime]] = []  # where organic orders give way to the Offer's outcome
        opted_out_at = None
        for moment in found:
            send_at = _send_time(moment.at)
            if send_at + HORIZON > end or (opted_out_at is not None and moment.at >= opted_out_at):
                continue
            if sends and moment.at < sends[-1] + HORIZON:
                continue
            key = (churned_at is not None and churned_at < moment.at, send_at.date())
            if key not in bases:
                bases[key] = ground_truth.organic_weekly_chance(traits, key[0], math.sqrt(season(key[1])))
            if rng.random() >= SEND_CHANCE:
                moments.append((customer.id, _iso(moment.at), moment.trigger, None, bases[key]))
                continue

            offer_id = len(offers) + 1
            offer_type = list(OfferType)[int(rng.integers(len(OfferType)))]
            params = _terms(rng, offer_type, moment.category, ctx)
            depth = ground_truth.offer_depth(offer_type, params, ctx.catalog.categories[moment.category])
            p = ground_truth.p_buy(ground_truth.with_base(gts[customer.id][offer_type], bases[key]), depth)
            moments.append((customer.id, _iso(moment.at), moment.trigger, offer_id, p))
            expires_at = send_at + timedelta(days=RULES.offer_validity_days)
            sends.append(send_at)
            event = partial(Event, customer.id, offer_id=offer_id)

            status, redeemed_at = OfferStatus.EXPIRED, None
            if rng.random() < p:
                status, redeemed_at = OfferStatus.REDEEMED, _between(rng, send_at, expires_at)
                new_events.append(event(_between(rng, send_at, redeemed_at), "offer_claimed"))
                products = by_category[moment.category]
                product = products[int(rng.integers(len(products)))]
                new_events += _redemption(
                    ctx, rng, customer.id, offer_id, offer_type, params, product, redeemed_at
                )
            elif rng.random() < OPT_OUT_CHANCE:
                status, opted_out_at = OfferStatus.DISMISSED, _between(rng, send_at, expires_at)
                new_events += [event(opted_out_at, "offer_dismissed"), event(opted_out_at, "opted_out")]
                opted_out.append(customer.id)
            elif rng.random() < CLAIM_WITHOUT_BUYING:
                status = OfferStatus.CLAIMED
                new_events.append(event(_between(rng, send_at, expires_at), "offer_claimed"))
            elif rng.random() < DISMISS_CHANCE:
                status = OfferStatus.DISMISSED
                new_events.append(event(_between(rng, send_at, expires_at), "offer_dismissed"))

            spans.append((send_at, redeemed_at or send_at + HORIZON))
            category = moment.category if offer_type == OfferType.PCT_CATEGORY else None
            worst, if_redeemed = offer_cost(offer_type, category, params, ctx.catalog, RULES)
            redeem_chance = min(max(BASE_BUY_CHANCE + lift_at(offer_type, depth), 0.0), 1.0)
            offers.append(
                (offer_id, _code(rng, codes), customer.id, str(offer_type), category, json.dumps(params))
                + (_iso(moment.at), _iso(send_at), _iso(expires_at), worst, if_redeemed * redeem_chance)
                + (str(status), _iso(redeemed_at) if redeemed_at else None)
            )
        removed += [(customer.id, o) for o in orders if any(lo <= o[1] < hi for lo, hi in spans)]

    ctx.conn.executemany(
        "INSERT INTO offers (id, code, customer_id, offer_type, category, params, created_at, send_at, expires_at,"
        " worst_case_cost, expected_cost, status, redeemed_at, rule_version, source)"
        f" VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '{OfferSource.HISTORY_RANDOM}')",
        offers,
    )
    ctx.conn.executemany(
        "INSERT INTO sim_history_moments (customer_id, at, trigger, offer_id, p_buy) VALUES (?, ?, ?, ?, ?)",
        moments,
    )
    gone = _remove_orders(ctx, ledger, removed, end)
    points = defaultdict(list)
    for e in new_events:
        if e.kind.startswith("points_"):
            points[e.customer_id].append(e)
        elif e.at >= end:
            ctx.scheduled[e.at.date()].append(e)
    rest = [e for e in new_events if e.at < end and not e.kind.startswith("points_")]
    insert_events(ctx.conn, sorted(rest, key=lambda e: (e.at, e.customer_id)))
    changed = {cid for cid, _ in removed} | {e.customer_id for e in new_events if e.kind == "order"}
    _replay_points(ctx, ledger, sorted(changed), gone, points, end)
    ctx.conn.executemany(
        "UPDATE customers SET opted_out = 1 WHERE id = ?", [(c,) for c in sorted(set(opted_out))]
    )
    update_customers(ctx)


def _load(ctx: GenContext) -> Ledger:
    """Orders, their follow-on events and every points event, plus each Customer's points at the history start
    (the end balance with the history's earns, burns and expiries undone)."""
    ledger = Ledger()
    kinds = ("order", "delivered", "return", "points_earned", "points_burned", "points_expired")
    query = (
        "SELECT id, customer_id, at, kind, category, product_id, amount FROM events"
        f" WHERE kind IN ({','.join('?' * len(kinds))}) ORDER BY id"
    )
    for eid, cid, at, kind, category, product, amount in ctx.conn.execute(query, kinds):
        at = datetime.fromisoformat(at)
        if kind == "order":
            ledger.orders[cid].append((eid, at, category, product, amount))
        elif kind in ("delivered", "return"):
            ledger.follow_ons[(cid, kind, product, amount)].append((eid, at))
        else:
            ledger.points[cid].append((eid, at, kind, category, amount))
            if kind != "points_expired":
                ledger.follow_ons[(cid, kind, at)].append((eid, at))

    for cid, sim in ctx.state.items():
        sign = {"points_earned": -1, "points_burned": 1, "points_expired": 1}
        events = ledger.points.get(cid, [])
        balance = sim.points_balance + sum(sign[kind] * n for _, _, kind, _, n in events)
        expire_at = None
        if balance:
            first_earn = next((at for _, at, kind, _, _ in events if kind == "points_earned"), None)
            first_expiry = next((at for _, at, kind, _, _ in events if kind == "points_expired"), None)
            if first_earn is None:
                expire_at = first_expiry or sim.points_expire_at
            elif first_expiry is not None and first_expiry <= first_earn:
                expire_at = first_expiry
            else:
                # Refreshed by that earn before it fell due; if the earn is removed, the points lapse there.
                expire_at = first_earn + timedelta(seconds=1)
        ledger.start_points[cid] = (round(balance), expire_at)
    return ledger


def _remove_orders(ctx: GenContext, ledger: Ledger, removed: list[tuple], end: datetime) -> set[int]:
    """Delete removed organic orders and their burn, delivery, points earned and return. Deliveries and returns
    still due after the history are taken out of `ctx.scheduled`. Returns the deleted event ids."""
    gone: set[int] = set()

    def take(key: tuple, after: datetime | None = None) -> None:
        found = ledger.follow_ons.get(key, [])
        for i, (eid, at) in enumerate(found):
            if after is None or at > after:
                gone.add(eid)
                del found[i]
                return

    for cid, (eid, at, category, product, amount) in removed:
        gone.add(eid)
        take((cid, "points_burned", at))
        delivered_at = at + timedelta(days=DELIVERY_DAYS)
        if delivered_at < end:
            take((cid, "delivered", product, amount))
            take((cid, "points_earned", delivered_at))
            before = len(gone)
            take((cid, "return", product, amount), after=delivered_at)
            if len(gone) == before:
                _unschedule(ctx, cid, "return", product, amount)
        else:
            _unschedule(ctx, cid, "delivered", product, amount)
    ctx.conn.executemany("DELETE FROM events WHERE id = ?", [(eid,) for eid in sorted(gone)])
    return gone


def _unschedule(ctx: GenContext, cid: str, kind: str, product: str, amount: float) -> None:
    for due in ctx.scheduled.values():
        for i, e in enumerate(due):
            if (e.customer_id, e.kind, e.product_id, e.amount) == (cid, kind, product, amount):
                del due[i]
                return


def _replay_points(
    ctx: GenContext,
    ledger: Ledger,
    changed: list[str],
    gone: set[int],
    new: dict[str, list[Event]],
    end: datetime,
) -> None:
    """Rebuild every points event for Customers whose orders changed, from their points at the history start, the
    earns and burns that remain and the redemption orders' ones. A burn needs 50 points and shrinks to the balance;
    points expire 180 days after the last earn. Earns due after the history wait in `ctx.scheduled`."""
    stale, rows = [], []
    last_second = end - timedelta(seconds=1)
    for cid in changed:
        steps = []
        for eid, at, kind, category, n in ledger.points.get(cid, []):
            stale.append(eid)
            if kind != "points_expired" and eid not in gone:
                steps.append((at, kind, category, n))
        for e in new.get(cid, []):
            if e.at < end:
                steps.append((e.at, e.kind, e.category, e.amount))
            else:
                ctx.scheduled[e.at.date()].append(e)
        steps.sort(key=lambda s: s[0])
        sim = ctx.state[cid]
        sim.points_balance, sim.points_expire_at = ledger.start_points[cid]
        rows += _points_in_order(cid, sim, steps, last_second)
    ctx.conn.executemany("DELETE FROM events WHERE id = ?", [(eid,) for eid in sorted(set(stale) - gone)])
    insert_events(ctx.conn, sorted(rows, key=lambda e: (e.at, e.customer_id)))


def _points_in_order(cid: str, sim: CustomerSim, steps: list[tuple], until: datetime) -> list[Event]:
    """Earns and burns applied to `sim` in time order, with the expiries between them, as points events."""
    out = []
    for at, kind, category, n in [*steps, (until, None, None, None)]:
        if sim.points_expire_at is not None and sim.points_expire_at <= at:
            if sim.points_balance:
                out.append(
                    Event(cid, sim.points_expire_at, "points_expired", amount=float(sim.points_balance))
                )
            sim.points_balance, sim.points_expire_at = 0, None
        if kind == "points_earned":
            sim.points_balance += int(n)
            sim.points_expire_at = at + POINTS_VALIDITY
            out.append(Event(cid, at, kind, category, amount=float(n)))
        elif kind == "points_burned" and sim.points_balance >= POINTS_BURN_MIN:
            burned = min(int(n), sim.points_balance)
            sim.points_balance -= burned
            out.append(Event(cid, at, kind, category, amount=float(burned)))
    return out


def _redemption(
    ctx: GenContext,
    rng: np.random.Generator,
    cid: str,
    offer_id: int,
    offer_type: OfferType,
    params: dict[str, float],
    product: Product,
    at: datetime,
) -> list[Event]:
    """The order an Offer is redeemed on, with its delivery, points earned (multiplied for a points Offer), maybe
    a points burn and a return, drawn as an organic order's are. Points events go to the replay."""
    category = product.category
    basket = ctx.catalog.categories[category].avg_basket * ctx.traits[cid].basket_size
    basket = max(product.price, basket * rng.lognormal(-(BASKET_SIGMA**2) / 2, BASKET_SIGMA))
    basket = float(round(max(basket, params.get("min_basket", 0.0))))
    cost = redemption_cost(offer_type, params, basket, RULES)
    delivered_at = at + timedelta(days=DELIVERY_DAYS)
    points = int(basket * POINTS_PER_RUPEE * params.get("multiplier", 1.0))
    events = [
        Event(cid, at, "order", category, product.id, basket, offer_id),
        Event(cid, at, "offer_redeemed", category, amount=round(cost, 2), offer_id=offer_id),
        Event(cid, delivered_at, "delivered", category, product.id, basket),
        Event(cid, delivered_at, "points_earned", category, amount=float(points)),
    ]
    if rng.random() < ctx.traits[cid].coupon_affinity:
        # The most points could cover; the replay cuts it to the balance then, as `session` does.
        most = int(basket * POINTS_BURN_MAX_SHARE / POINT_VALUE)
        events.append(Event(cid, at, "points_burned", category, amount=float(most)))
    if rng.random() < RETURN_RATE.get(category, 0.05):
        returned_at = delivered_at + timedelta(
            days=int(rng.integers(*RETURN_DAYS)), minutes=int(rng.integers(0, 600))
        )
        events.append(Event(cid, returned_at, "return", category, product.id, basket))
    return events


def _terms(
    rng: np.random.Generator, offer_type: OfferType, category: str, ctx: GenContext
) -> dict[str, float]:
    """Depth uniform in a plausible range. A % off cap and a flat amount's minimum basket follow the live Rules'
    shapes (the rules chooser's cap, the margin floor's minimum basket)."""
    if offer_type == OfferType.PCT_CATEGORY:
        pct = float(rng.integers(PCT_RANGE[0], PCT_RANGE[1] + 1))
        expected = pct * ctx.catalog.categories[category].avg_basket / 100
        cap = min(max(math.ceil(expected / CAP_STEP) * CAP_STEP, MIN_CAP), RULES.per_offer_cost_cap)
        return {"pct": pct, "cap": float(cap)}
    if offer_type == OfferType.FLAT_ABOVE_MIN:
        amount = float(10 * rng.integers(FLAT_RANGE[0] // 10, FLAT_RANGE[1] // 10 + 1))
        cats = ctx.catalog.categories.values()
        room = sum(c.margin_pct for c in cats) / len(cats) - RULES.margin_floor_pct
        return {"amount": amount, "min_basket": float(math.ceil(amount / (room / 100) / 10) * 10)}
    if offer_type == OfferType.POINTS_MULTIPLIER:
        return {"multiplier": round(float(rng.uniform(*POINTS_RANGE)), 1)}
    return {}


def _long_gaps(
    signup_at: datetime, order_ats: list[datetime], start: date, end: datetime, category: str
) -> list[Moment]:
    """Every 45 days without an order, counted from signup and from each order, inside the history."""
    window_start = datetime.combine(start, time())
    marks = [signup_at, *sorted(order_ats), end]
    out = []
    for since, until in itertools.pairwise(marks):
        skip = max(1, math.ceil((window_start - since) / LONG_GAP))
        at = since + skip * LONG_GAP
        while at < until:
            out.append(Moment(at, "long_gap", category))
            at += LONG_GAP
    return out


def _broadcast_slots(start: date, end: date) -> list[datetime]:
    day = start + timedelta(days=(BROADCAST_WEEKDAY - start.weekday()) % 7)
    out = []
    while day < end:
        out.append(datetime.combine(day, time(BROADCAST_HOUR)))
        day += timedelta(days=7)
    return out


def _send_time(at: datetime) -> datetime:
    """`at` if inside the send hours, else the next opening."""
    opening = at.replace(hour=RULES.send_hour_start, minute=0, second=0, microsecond=0)
    if at.hour < RULES.send_hour_start:
        return opening
    if at.hour >= RULES.send_hour_end:
        return opening + timedelta(days=1)
    return at


def _between(rng: np.random.Generator, lo: datetime, hi: datetime) -> datetime:
    seconds = int((hi - lo).total_seconds())
    return lo + timedelta(seconds=int(rng.integers(0, seconds))) if seconds > 0 else lo


def _code(rng: np.random.Generator, taken: set[str]) -> str:
    while True:
        code = CODE_PREFIX + "".join(CODE_ALPHABET[i] for i in rng.integers(0, len(CODE_ALPHABET), 6))
        if code not in taken:
            taken.add(code)
            return code


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="seconds")
