"""Calibration check (PLAN §2.2): measure the generated history against the calibration targets in
`docs/research/ecommerce-benchmarks.md` ("Suggested calibration targets"), one `Metric` per target figure.

The history runs from the first event's day to the Simulation Clock's start; live events after it are ignored.
Targets the data can't express (no past Offers, a history too short for the festive window) are left out.
Category splits are the source's judgement: they are reported but never fail `calibrate --strict`.
Reads the simulator's hidden tables, so only the simulator and `commands` import it.
"""

from __future__ import annotations

import itertools
import sqlite3
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from offer_engine import clock
from offer_engine.domain import OfferType
from offer_engine.sim.ground_truth import TARGET_SHARES, TYPICAL_PCT, GroundTruth, p_buy

PCT, COUNT = "%", "×"


@dataclass(frozen=True)
class Metric:
    id: str  # the target number in the benchmarks table, e.g. "5a"
    name: str
    value: float
    lo: float
    hi: float
    unit: str = PCT  # PCT values are fractions; COUNT values are plain numbers
    split: bool = False  # a category split: reported, never fails --strict

    @property
    def passed(self) -> bool:
        return self.lo <= self.value <= self.hi


# Target ranges, by target number. Fractions unless the unit says otherwise.
CONVERSION = (0.012, 0.025)  # 1
WEEKLY_BASE = {"mean": (0.04, 0.08), "median": (0.01, 0.03), "top decile mean": (0.25, 0.50)}  # 1a
CART_ABANDONMENT = (0.70, 0.80)  # 2
CART_RECOVERY = (0.08, 0.15)  # 3, chat channel (Telegram)
RECOVERED_ANYWAY = (0.45, 0.75)  # 3a
REDEMPTION_PER_SEND = {"targeted": (0.015, 0.05), "broadcast": (0.001, 0.01)}  # 4
REPEAT_90_DAYS = (0.20, 0.35)  # 5
REPEAT_90_DAYS_BY_CATEGORY = {  # 5, split
    "grocery": (0.40, 0.60),
    "beauty": (0.25, 0.40),
    "fashion": (0.15, 0.30),
    "home": (0.10, 0.20),
    "electronics": (0.05, 0.15),
}
ORDERS_PER_YEAR = (4.0, 9.0)  # 5a
ORDERS_PER_YEAR_BY_CATEGORY = {  # 5a, split
    "grocery": (24.0, 40.0),
    "fashion": (3.0, 6.0),
    "beauty": (3.0, 5.0),
    "home": (1.0, 3.0),
    "electronics": (1.0, 2.0),
}
LAPSE = (0.35, 0.50)  # 6
ONE_TIME = (0.50, 0.65)  # 6
GROSS_MARGIN = {  # 7
    "grocery": (0.12, 0.18),
    "electronics": (0.08, 0.15),
    "fashion": (0.40, 0.50),
    "beauty": (0.35, 0.45),
    "home": (0.25, 0.35),
}
SPEND_SHARE = {0.20: (0.65, 0.75), 0.10: (0.45, 0.60), 0.01: (0.10, 0.20)}  # 8
# 9: Response Class shares are ground_truth.TARGET_SHARES.
BLANKET_LIFT = (0.30, 1.20)  # 9, relative
SURE_THING_REDEEMERS = (0.45, 0.75)  # 9
FESTIVE_SHARE = (0.15, 0.20)  # 10
PEAK_WEEK_SHARE = (0.05, 0.09)  # 10: "~7%", our range
BREAKAGE = (0.25, 0.35)  # 11
NEVER_BURN = (0.20, 0.30)  # 11
OPT_OUT_PER_MESSAGE = (0.005, 0.015)  # 12, chat channel (Telegram)

# How the targets are read on a single history.
LAPSE_COHORT_DAYS = 90  # 6: ordered in the history's first 90 days, lapsed by its end (the next ~9 months)
LAPSE_CAP_DAYS = 180  # 6: lapsed = no order in 2× the category's median gap, capped at 180 days
FESTIVE = ((9, 15), (11, 7))  # 10: mid-Sep to early Nov, (month, day) inclusive
PEAK_WEEK = ((11, 1), (11, 7))
CONVERSION_TOP, CONVERSION_BOTTOM = ("grocery", "beauty"), ("home", "electronics")  # 1


def measure(conn: sqlite3.Connection, end: datetime = clock.START) -> list[Metric]:
    """Every target the history before `end` can express, in target order."""
    first = conn.execute("SELECT MIN(at) FROM events WHERE at < ?", (_iso(end),)).fetchone()[0]
    if first is None:
        return []
    window = Window(datetime.fromisoformat(first).replace(hour=0, minute=0, second=0), end)
    orders = _orders(conn, window)
    return [
        *conversion(conn, window),
        *weekly_base(conn, window),
        *cart_abandonment(conn, window),
        *cart_recovery(conn),
        *redemption_per_send(conn),
        *repeat_90_days(conn, window, orders),
        *orders_per_year(window, orders),
        *lapse(conn, window, orders),
        *margins(conn),
        *spend_concentration(orders),
        *response_classes(conn),
        *seasonality(window, orders),
        *points(conn, window),
        *opt_outs(conn),
    ]


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime

    @property
    def years(self) -> float:
        return (self.end - self.start).days / 365


@dataclass(frozen=True)
class Order:
    customer_id: str
    at: datetime
    category: str
    amount: float


def _orders(conn: sqlite3.Connection, window: Window) -> dict[str, list[Order]]:
    """Every order in the history by Customer, in time order."""
    out: dict[str, list[Order]] = defaultdict(list)
    query = (
        "SELECT customer_id, at, category, amount FROM events WHERE kind = 'order' AND at < ? ORDER BY at, id"
    )
    for cid, at, category, amount in conn.execute(query, (_iso(window.end),)):
        out[cid].append(Order(cid, datetime.fromisoformat(at), category, amount))
    return out


# --- 1, 1a, 2: the organic funnel ---------------------------------------------------------------------


def conversion(conn: sqlite3.Connection, window: Window) -> list[Metric]:
    """1: orders per session, overall; grocery and beauty should convert above home and electronics."""
    rows = conn.execute(
        "SELECT category, SUM(kind = 'session'), SUM(kind = 'order') FROM events"
        " WHERE kind IN ('session', 'order') AND at < ? GROUP BY category",
        (_iso(window.end),),
    ).fetchall()
    sessions = sum(r[1] for r in rows)
    if not sessions:
        return []
    out = [Metric("1", "Session-to-order conversion", sum(r[2] for r in rows) / sessions, *CONVERSION)]
    rate = {r[0]: r[2] / r[1] for r in rows if r[1]}
    if all(c in rate for c in CONVERSION_TOP + CONVERSION_BOTTOM):
        gap = min(rate[c] for c in CONVERSION_TOP) - max(rate[c] for c in CONVERSION_BOTTOM)
        out.append(
            Metric("1", "Grocery, beauty convert above home, electronics (gap)", gap, 0.0, 1.0, split=True)
        )
    return out


def weekly_base(conn: sqlite3.Connection, window: Window) -> list[Metric]:
    """1a: Ground Truth's weekly no-offer purchase chance across Customers active at the end of the history."""
    bases = sorted(
        (
            row[0]
            for row in conn.execute(
                "SELECT g.base FROM sim_ground_truth g JOIN sim_customer_traits t USING (customer_id)"
                " WHERE g.offer_type = 'nudge' AND (t.churned_at IS NULL OR t.churned_at >= ?)",
                (_iso(window.end),),
            )
        ),
        reverse=True,
    )
    if not bases:
        return []
    top = bases[: max(1, len(bases) // 10)]
    values = {
        "mean": statistics.fmean(bases),
        "median": statistics.median(bases),
        "top decile mean": statistics.fmean(top),
    }
    return [
        Metric("1a", f"Weekly no-offer purchase chance, {k}", values[k], *WEEKLY_BASE[k]) for k in WEEKLY_BASE
    ]


def cart_abandonment(conn: sqlite3.Connection, window: Window) -> list[Metric]:
    """2: abandoned carts per add-to-cart."""
    abandoned, carts = conn.execute(
        "SELECT SUM(kind = 'cart_abandoned'), SUM(kind = 'add_to_cart') FROM events"
        " WHERE kind IN ('cart_abandoned', 'add_to_cart') AND at < ?",
        (_iso(window.end),),
    ).fetchone()
    return [Metric("2", "Cart abandonment", abandoned / carts, *CART_ABANDONMENT)] if carts else []


# --- 3, 3a, 4, 12: past Offers ------------------------------------------------------------------------


def cart_recovery(conn: sqlite3.Connection) -> list[Metric]:
    """3: Redemption per past Offer sent on an abandoned cart. 3a: the share of those Redemptions that would have
    happened without the Offer, from the randomised draw: mean Ground Truth chance at carts left without an Offer
    over the mean at carts that got one."""
    sent, redeemed, p_sent, p_unsent, unsent = conn.execute(
        "SELECT COUNT(m.offer_id), SUM(o.status = 'redeemed'),"
        " AVG(CASE WHEN m.offer_id IS NOT NULL THEN m.p_buy END), AVG(CASE WHEN m.offer_id IS NULL THEN m.p_buy END),"
        " SUM(m.offer_id IS NULL)"
        " FROM sim_history_moments m LEFT JOIN offers o ON o.id = m.offer_id WHERE m.trigger = 'cart_abandoned'"
    ).fetchone()
    if not sent:
        return []
    out = [
        Metric(
            "3", "Cart recovery: Redemption per Offer on an abandoned cart", redeemed / sent, *CART_RECOVERY
        )
    ]
    if unsent and p_sent:
        out.append(
            Metric(
                "3a", "Recovered carts that would have bought anyway", p_unsent / p_sent, *RECOVERED_ANYWAY
            )
        )
    return out


def redemption_per_send(conn: sqlite3.Connection) -> list[Metric]:
    """4: Redemption per past Offer sent, targeted (abandoned cart, long gap) and broadcast."""
    rows = conn.execute(
        "SELECT CASE m.trigger WHEN 'broadcast' THEN 'broadcast' ELSE 'targeted' END, COUNT(*),"
        " SUM(o.status = 'redeemed') FROM sim_history_moments m JOIN offers o ON o.id = m.offer_id GROUP BY 1"
    ).fetchall()
    found = {group: redeemed / sent for group, sent, redeemed in rows}
    return [
        Metric("4", f"Redemption per send, {group}", found[group], *REDEMPTION_PER_SEND[group])
        for group in REDEMPTION_PER_SEND
        if group in found
    ]


def opt_outs(conn: sqlite3.Connection) -> list[Metric]:
    """12: opt-outs per past Offer sent."""
    sent, opted = conn.execute(
        "SELECT COUNT(*), (SELECT COUNT(*) FROM events e JOIN offers p ON p.id = e.offer_id"
        "  WHERE e.kind = 'opted_out' AND p.source = 'history_random')"
        " FROM offers WHERE source = 'history_random'"
    ).fetchone()
    return [Metric("12", "Opt-out per message", opted / sent, *OPT_OUT_PER_MESSAGE)] if sent else []


# --- 5, 5a, 6, 8, 10: orders --------------------------------------------------------------------------


def repeat_90_days(conn: sqlite3.Connection, window: Window, orders: dict[str, list[Order]]) -> list[Metric]:
    """5: Customers who signed up in the history and whose first order is 90+ days before its end: the share who
    order again within 90 days of it. Split by the first order's category."""
    new = _signed_up(conn, window.start, window.end)
    repeat: dict[str, list[bool]] = defaultdict(list)
    for cid in sorted(new & orders.keys()):
        first, *rest = orders[cid]
        horizon = first.at + timedelta(days=90)
        if horizon <= window.end:
            repeat[first.category].append(any(o.at <= horizon for o in rest))
    flags = [f for group in repeat.values() for f in group]
    if not flags:
        return []
    out = [Metric("5", "90-day repeat among new Customers", _mean(flags), *REPEAT_90_DAYS)]
    for category, (lo, hi) in REPEAT_90_DAYS_BY_CATEGORY.items():
        if repeat[category]:
            out.append(
                Metric(
                    "5",
                    f"90-day repeat, first order in {category}",
                    _mean(repeat[category]),
                    lo,
                    hi,
                    split=True,
                )
            )
    return out


def orders_per_year(window: Window, orders: dict[str, list[Order]]) -> list[Metric]:
    """5a: orders per year per Customer who ordered in the history; per category, per Customer who ordered in it."""
    if not orders:
        return []
    per_year = [len(o) / window.years for o in orders.values()]
    out = [
        Metric(
            "5a", "Orders per active Customer per year", statistics.fmean(per_year), *ORDERS_PER_YEAR, COUNT
        )
    ]
    for category, (lo, hi) in ORDERS_PER_YEAR_BY_CATEGORY.items():
        counts = [n for o in orders.values() if (n := sum(x.category == category for x in o))]
        if counts:
            value = statistics.fmean(counts) / window.years
            out.append(
                Metric("5a", f"Orders per {category} buyer per year", value, lo, hi, COUNT, split=True)
            )
    return out


def lapse(conn: sqlite3.Connection, window: Window, orders: dict[str, list[Order]]) -> list[Metric]:
    """6: of established Customers (signed up before the history) who ordered in its first 90 days, the share lapsed
    at its end: no order in 2× their main category's median gap, capped at 180 days. New Customers are left out:
    most stay one-time, which the second figure measures. A category's median gap is the median over its repeat buyers of
    each one's median days between orders in it, so heavy buyers don't set it alone. And of Customers who signed
    up in the history's first half and ordered, the share who ordered only once."""
    gaps: dict[str, list[float]] = defaultdict(list)
    for customer_orders in orders.values():
        by_category: dict[str, list[datetime]] = defaultdict(list)
        for o in customer_orders:
            by_category[o.category].append(o.at)
        for category, ats in by_category.items():
            if len(ats) > 1:
                days = [(b - a).total_seconds() / 86_400 for a, b in itertools.pairwise(ats)]
                gaps[category].append(statistics.median(days))
    limit = {c: min(LAPSE_CAP_DAYS, 2 * statistics.median(g)) for c, g in gaps.items()}

    cohort_end = window.start + timedelta(days=LAPSE_COHORT_DAYS)
    established = _signed_up(conn, None, window.start)
    lapsed = []
    for cid in sorted(established & orders.keys()):
        customer_orders = orders[cid]
        if customer_orders[0].at >= cohort_end:
            continue
        main = Counter(o.category for o in customer_orders).most_common(1)[0][0]
        idle = (window.end - customer_orders[-1].at).total_seconds() / 86_400
        lapsed.append(idle > limit.get(main, LAPSE_CAP_DAYS))

    half = window.start + (window.end - window.start) / 2
    early = _signed_up(conn, window.start, half)
    one_time = [len(orders[cid]) == 1 for cid in sorted(early & orders.keys())]

    out = []
    if lapsed:
        out.append(Metric("6", "Lapse: early buyers lapsed by the end", _mean(lapsed), *LAPSE))
    if one_time:
        out.append(Metric("6", "New Customers who stay one-time", _mean(one_time), *ONE_TIME))
    return out


def spend_concentration(orders: dict[str, list[Order]]) -> list[Metric]:
    """8: the top 20%, 10% and 1% of buyers' share of order value."""
    spend = sorted((sum(o.amount for o in os) for os in orders.values()), reverse=True)
    total = sum(spend)
    if not total:
        return []
    return [
        Metric(
            "8",
            f"Top {top:.0%} of Customers' share of spend",
            sum(spend[: max(1, round(len(spend) * top))]) / total,
            lo,
            hi,
        )
        for top, (lo, hi) in SPEND_SHARE.items()
    ]


def seasonality(window: Window, orders: dict[str, list[Order]]) -> list[Metric]:
    """10: the festive window's and the peak sale week's share of a year's order value. Needs a full year."""
    if window.years < 1:
        return []
    year_start = window.end - timedelta(days=365)
    gmv = festive = peak = 0.0
    for o in (o for os in orders.values() for o in os if o.at >= year_start):
        gmv += o.amount
        festive += o.amount * _in(o.at.date(), FESTIVE)
        peak += o.amount * _in(o.at.date(), PEAK_WEEK)
    if not gmv:
        return []
    return [
        Metric("10", "Festive window's share of GMV", festive / gmv, *FESTIVE_SHARE),
        Metric("10", "Peak sale week's share of GMV", peak / gmv, *PEAK_WEEK_SHARE),
    ]


# --- 7, 9, 11: catalog, Ground Truth, points -----------------------------------------------------------


def margins(conn: sqlite3.Connection) -> list[Metric]:
    """7: gross margin per category."""
    return [
        Metric("7", f"Gross margin, {name}", margin / 100, *GROSS_MARGIN[name])
        for name, margin in conn.execute("SELECT name, margin_pct FROM categories ORDER BY name")
        if name in GROSS_MARGIN
    ]


def response_classes(conn: sqlite3.Connection) -> list[Metric]:
    """9: Response Class shares; a blanket typical Offer's relative Lift; the Sure Things' share of its redeemers."""
    counts = dict(
        conn.execute("SELECT response_class, COUNT(*) FROM sim_response_class GROUP BY 1").fetchall()
    )
    total = sum(counts.values())
    if not total:
        return []
    out = [
        Metric("9", f"Response Class share, {name.replace('_', ' ')}", counts.get(name, 0) / total, lo, hi)
        for name, (lo, hi) in TARGET_SHARES.items()
    ]
    base = with_offer = sure = 0.0
    query = (
        "SELECT g.customer_id, g.base, g.max_lift, g.k, r.response_class FROM sim_ground_truth g"
        " JOIN sim_response_class r USING (customer_id) WHERE g.offer_type = 'pct_category'"
    )
    for cid, b, max_lift, k, cls in conn.execute(query):
        p = p_buy(GroundTruth(cid, OfferType.PCT_CATEGORY, b, max_lift, k), TYPICAL_PCT / 100)
        base += b
        with_offer += p
        sure += p if cls == "sure_thing" else 0.0
    if base:
        out.append(
            Metric(
                "9", f"Blanket {TYPICAL_PCT:.0f}% Offer: relative Lift", with_offer / base - 1, *BLANKET_LIFT
            )
        )
    if with_offer:
        out.append(
            Metric("9", "Sure Things' share of its redeemers", sure / with_offer, *SURE_THING_REDEEMERS)
        )
    return out


def points(conn: sqlite3.Connection, window: Window) -> list[Metric]:
    """11: for Customers who signed up in the history, whose whole membership it shows: points expired over points
    burned or expired; and of those who earned points on an order, the share who never burned any."""
    new = _signed_up(conn, window.start, window.end)
    used = defaultdict(float)
    earned_on_orders, burners = set(), set()
    query = (
        "SELECT customer_id, kind, category, amount FROM events"
        " WHERE kind IN ('points_earned', 'points_burned', 'points_expired') AND at < ?"
    )
    for cid, kind, category, amount in conn.execute(query, (_iso(window.end),)):
        if cid not in new:
            continue
        if kind == "points_earned":
            if category is not None:
                earned_on_orders.add(cid)
            continue
        used[kind] += amount
        if kind == "points_burned":
            burners.add(cid)
    out = []
    if used:
        expired = used["points_expired"]
        out.append(
            Metric(
                "11", "Points breakage, new Customers", expired / (used["points_burned"] + expired), *BREAKAGE
            )
        )
    if earned_on_orders:
        never = len(earned_on_orders - burners) / len(earned_on_orders)
        out.append(Metric("11", "New Customers earning points who never burn", never, *NEVER_BURN))
    return out


def _signed_up(conn: sqlite3.Connection, lo: datetime | None, hi: datetime) -> set[str]:
    """Customers (not Tester copies) who signed up in [lo, hi); from the beginning when `lo` is None."""
    query = "SELECT id FROM customers WHERE is_tester_copy = 0 AND signup_at >= ? AND signup_at < ?"
    return {row[0] for row in conn.execute(query, (_iso(lo) if lo else "", _iso(hi)))}


def _in(day: date, span: tuple[tuple[int, int], tuple[int, int]]) -> bool:
    return span[0] <= (day.month, day.day) <= span[1]


def _mean(flags: list[bool]) -> float:
    return sum(flags) / len(flags)


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="seconds")
