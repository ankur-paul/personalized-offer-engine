"""Offer outcomes (PLAN §2.5, §4.1, §4.3; ADR 0002, 0004): every simulated hour, sent Offers resolve into Claims,
Redemptions and expiry.

Each Offer's fate is drawn once into `sim_offer_fates`, and the hook acts on each of its times once the clock has
passed it, so a clock stopped mid-day changes nothing. A Customer without a chat buys with Ground Truth chance
`p_buy` at a time inside the validity window, as past Offers do (T14): a buyer claims first, 25% of the others
claim without buying, and a few dismiss or opt out. A Tester's fate is drawn when they claim, with the chance of
buying given a Claim, and the Offer Bot tells them about the order. A Customer Bot's fate comes from its role-play
(T24); until then its Offer only expires.

The Offer decides whether the Customer buys in the 7 days after the send (docs/QnA.md Q39): organic orders stop
from the send until the Redemption, or for all 7 days if they don't buy. `no_order_ids` and `trim_orders` apply
that to the day-step's draws. `p_buy` uses the Customer's base at the send (Q40).
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import numpy as np

from offer_engine.db import load_catalog
from offer_engine.domain import Catalog, Event, OfferSource, OfferStatus, OfferType
from offer_engine.rules_store import current_rules
from offer_engine.sim import ground_truth
from offer_engine.sim.generate.customers import Traits
from offer_engine.sim.generate.history import DELIVERY_DAYS, POINTS_PER_RUPEE, insert_events, season
from offer_engine.sim.generate.past_offers import (
    CLAIM_WITHOUT_BUYING,
    DISMISS_CHANCE,
    HORIZON,
    OPT_OUT_CHANCE,
)
from offer_engine.sim.world.offer_economics import redemption_order
from offer_engine.sim.world.pending import add_pending

if TYPE_CHECKING:
    from offer_engine.sim.world.day_step import DayReport

GROUND_TRUTH, TESTER_CLAIM, BOT_ROLEPLAY = "ground_truth", "tester_claim", "bot_roleplay"
ACTIVE = (OfferStatus.SENT, OfferStatus.CLAIMED)
UNREDEEMED = (OfferStatus.QUEUED, OfferStatus.SENT, OfferStatus.CLAIMED)


@dataclass(frozen=True)
class Fate:
    offer_id: int
    buys: bool
    p_used: float
    source: str
    buy_at: datetime | None = None
    claim_at: datetime | None = None
    dismiss_at: datetime | None = None
    opts_out: bool = False


@dataclass(frozen=True)
class SimCustomer:
    """What the simulator knows about the Customer behind an Offer (a Tester copy's source)."""

    id: str
    traits: Traits
    churned_at: datetime | None
    truth: dict[OfferType, ground_truth.GroundTruth]


def on_hour(conn: sqlite3.Connection, now: datetime, report: DayReport, rng: np.random.Generator) -> None:
    """Draw fates for newly sent and newly claimed Offers, act on every fate time up to `now`, expire the rest, and
    add `claimed`, `dismissed`, `opted_out`, `redeemed` and `expired` to `report.counts`."""
    catalog: Catalog | None = None
    for offer in _unfated(conn, now):
        catalog = catalog or load_catalog(conn)
        fate = draw_fate(conn, offer, catalog, now, rng)
        if fate is not None:
            save_fate(conn, fate)
            cancel_orders(conn, offer["customer_id"], *_window(offer, fate))

    counts = report.counts
    counts["claimed"] += _claim_due(conn, now)
    dismissed, opted_out = _dismiss_due(conn, now)
    counts["dismissed"] += dismissed
    counts["opted_out"] += opted_out
    due = _redemptions_due(conn, now)
    if due:
        catalog = catalog or load_catalog(conn)
        for offer in due:
            counts["claimed"] += redeem(conn, offer, catalog, rng)
        counts["redeemed"] += len(due)
        counts["order"] += len(due)
    counts["expired"] += _expire(conn, now)
    conn.commit()


def draw_fate(
    conn: sqlite3.Connection, offer: sqlite3.Row, catalog: Catalog, now: datetime, rng: np.random.Generator
) -> Fate | None:
    """A Customer without a chat: buy with `p_buy` inside the validity window. A Tester who claimed: buy with
    p / (p + 0.25 · (1 − p)), the chance of buying given a Claim, in the rest of the window. None without Ground
    Truth."""
    customer = sim_customer(conn, offer["customer_id"])
    if customer is None:
        return None
    sent_at = _time(offer["sent_at"]) or _time(offer["send_at"])
    expires_at = _time(offer["expires_at"])
    p = buy_chance(customer, offer, catalog, sent_at)
    if offer["chat_kind"] == "tester":
        p_claimed = p / (p + CLAIM_WITHOUT_BUYING * (1 - p)) if p > 0 else 0.0
        if now < expires_at and rng.random() < p_claimed:
            return Fate(offer["id"], True, p_claimed, TESTER_CLAIM, buy_at=_between(rng, now, expires_at))
        return Fate(offer["id"], False, p_claimed, TESTER_CLAIM)

    if rng.random() < p:
        buy_at = _between(rng, sent_at, expires_at)
        return Fate(offer["id"], True, p, GROUND_TRUTH, buy_at, _between(rng, sent_at, buy_at))
    if rng.random() < OPT_OUT_CHANCE:
        return Fate(
            offer["id"], False, p, GROUND_TRUTH, dismiss_at=_between(rng, sent_at, expires_at), opts_out=True
        )
    if rng.random() < CLAIM_WITHOUT_BUYING:
        return Fate(offer["id"], False, p, GROUND_TRUTH, claim_at=_between(rng, sent_at, expires_at))
    if rng.random() < DISMISS_CHANCE:
        return Fate(offer["id"], False, p, GROUND_TRUTH, dismiss_at=_between(rng, sent_at, expires_at))
    return Fate(offer["id"], False, p, GROUND_TRUTH)


def buy_chance(customer: SimCustomer, offer: sqlite3.Row, catalog: Catalog, at: datetime) -> float:
    """Ground Truth's 7-day chance of buying with this Offer, at the Customer's base on `at`'s day."""
    lapsed = customer.churned_at is not None and customer.churned_at < at
    base = ground_truth.organic_weekly_chance(customer.traits, lapsed, math.sqrt(season(at.date())))
    offer_type = OfferType(offer["offer_type"])
    category = catalog.categories[redemption_category(offer, catalog, customer.traits)]
    depth = ground_truth.offer_depth(offer_type, json.loads(offer["params"]), category)
    return ground_truth.p_buy(ground_truth.with_base(customer.truth[offer_type], base), depth)


def save_fate(conn: sqlite3.Connection, fate: Fate) -> None:
    """Record an Offer's fate; the hook acts on its times from the next hour. T24 writes bot role-play fates here."""
    conn.execute(
        "INSERT INTO sim_offer_fates (offer_id, buys, buy_at, claim_at, dismiss_at, opts_out, p_used, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            fate.offer_id,
            int(fate.buys),
            _iso(fate.buy_at),
            _iso(fate.claim_at),
            _iso(fate.dismiss_at),
            int(fate.opts_out),
            fate.p_used,
            fate.source,
        ),
    )


def redeem(conn: sqlite3.Connection, offer: sqlite3.Row, catalog: Catalog, rng: np.random.Generator) -> int:
    """The Redemption at the fate's `buy_at`: an `order` (basket before the discount) and `offer_redeemed` (the
    Offer's cost), with the delivery due 3 days later. A Tester hears about it through the outbox. Returns 1 if
    the Offer was claimed here first, so every Redeemer counts as Claimed."""
    at = _time(offer["buy_at"])
    customer = sim_customer(conn, offer["customer_id"])
    category = catalog.categories[redemption_category(offer, catalog, customer.traits if customer else None)]
    products = sorted(
        (p for p in catalog.products.values() if p.category == category.name), key=lambda p: p.id
    )
    product = products[int(rng.integers(len(products)))]
    params = json.loads(offer["params"])
    offer_type = OfferType(offer["offer_type"])
    order = redemption_order(
        offer_type,
        params,
        category,
        product,
        rng,
        customer.traits.basket_size if customer else 1.0,
        current_rules(conn)[1],
    )

    claimed_here = offer["status"] == OfferStatus.SENT
    events = [
        Event(offer["customer_id"], at, "offer_claimed", category.name, offer_id=offer["id"])
    ] * claimed_here
    events += [
        Event(offer["customer_id"], at, "order", category.name, product.id, order.basket, offer["id"]),
        Event(
            offer["customer_id"],
            at,
            "offer_redeemed",
            category.name,
            amount=round(order.discount, 2),
            offer_id=offer["id"],
        ),
    ]
    insert_events(conn, events)
    conn.execute(
        "UPDATE offers SET status = ?, redeemed_at = ? WHERE id = ?",
        (OfferStatus.REDEEMED, _iso(at), offer["id"]),
    )
    if customer is not None and customer.id == offer["customer_id"]:
        delivered_at = at + timedelta(days=DELIVERY_DAYS)
        later = [Event(customer.id, delivered_at, "delivered", category.name, product.id, order.basket)]
        bonus = int(order.basket * POINTS_PER_RUPEE * (params.get("multiplier", 1.0) - 1))
        if bonus > 0:
            later.append(
                Event(customer.id, delivered_at, "points_earned", category.name, amount=float(bonus))
            )
        add_pending(conn, later, drawn=False)
    if offer["chat_kind"] == "tester":
        saved = f" You saved ₹{order.discount:,.0f}." if order.discount >= 0.5 else ""
        conn.execute(
            "INSERT INTO outbox (chat_id, text, created_at) VALUES (?, ?, ?)",
            (
                offer["chat_id"],
                f"Simulated order: ₹{order.basket:,.0f} basket, code {offer['code']} used.{saved}",
                _iso(at),
            ),
        )
    return int(claimed_here)


def redemption_category(offer: sqlite3.Row, catalog: Catalog, traits: Traits | None) -> str:
    """The Offer's category, else its first featured product's, else the Customer's favourite."""
    if offer["category"] in catalog.categories:
        return offer["category"]
    for product_id in json.loads(offer["featured_product_ids"]):
        if product_id in catalog.products:
            return catalog.products[product_id].category
    if traits is not None:
        return max(traits.category_affinity, key=traits.category_affinity.get)
    return min(catalog.categories)


def sim_customer(conn: sqlite3.Connection, customer_id: str) -> SimCustomer | None:
    row = conn.execute(
        "SELECT t.*, COALESCE(c.source_customer_id, c.id) AS sim_id FROM customers c "
        "JOIN sim_customer_traits t ON t.customer_id = COALESCE(c.source_customer_id, c.id) WHERE c.id = ?",
        (customer_id,),
    ).fetchone()
    if row is None:
        return None
    truth = ground_truth.load(conn, row["sim_id"])
    if not truth:
        return None
    traits = Traits(
        visit_rate=row["visit_rate"],
        buy_propensity=row["buy_propensity"],
        basket_size=row["basket_size"],
        category_affinity=json.loads(row["category_affinity"]),
        coupon_affinity=row["coupon_affinity"],
        churn_hazard=row["churn_hazard"],
    )
    return SimCustomer(row["sim_id"], traits, _time(row["churned_at"]), truth)


# --- Organic orders the Offer replaces (Q39) ---------------------------------------------------


def order_windows(
    conn: sqlite3.Connection, since: datetime, until: datetime
) -> list[tuple[str, datetime, datetime]]:
    """(Customer ID, from, to) for each fated Offer whose window overlaps [since, until): from the send to the
    Redemption, or 7 days for a Customer who doesn't buy."""
    rows = conn.execute(
        "SELECT o.customer_id, o.sent_at, o.send_at, f.buys, f.buy_at FROM sim_offer_fates f "
        "JOIN offers o ON o.id = f.offer_id WHERE COALESCE(o.sent_at, o.send_at) < ? "
        "AND COALESCE(o.sent_at, o.send_at) >= ? ORDER BY o.id",
        (_iso(until), _iso(since - HORIZON)),
    )
    windows = []
    for row in rows:
        lo = _time(row["sent_at"]) or _time(row["send_at"])
        hi = _time(row["buy_at"]) if row["buys"] else lo + HORIZON
        if hi > since:
            windows.append((row["customer_id"], lo, hi))
    return windows


def no_order_ids(conn: sqlite3.Connection, day_start: datetime) -> set[str]:
    """Customers who place no organic order all day: an Offer's window covers it, or an active Offer still waits
    for its fate (a Customer Bot's role-play, a Tester's Claim)."""
    day_end = day_start + timedelta(days=1)
    covered = {
        cid for cid, lo, hi in order_windows(conn, day_start, day_end) if lo <= day_start and hi >= day_end
    }
    waiting = conn.execute(
        f"SELECT DISTINCT o.customer_id FROM offers o LEFT JOIN sim_offer_fates f ON f.offer_id = o.id "
        f"WHERE f.offer_id IS NULL AND o.status IN ({','.join('?' * len(ACTIVE))}) AND o.expires_at > ?",
        (*ACTIVE, _iso(day_start)),
    )
    return covered | {row[0] for row in waiting}


def trim_orders(conn: sqlite3.Connection, day_start: datetime) -> None:
    """Cancel the day's drawn organic orders inside a window that covers only part of it."""
    for customer_id, lo, hi in order_windows(conn, day_start, day_start + timedelta(days=1)):
        cancel_orders(conn, customer_id, lo, hi)


def cancel_orders(conn: sqlite3.Connection, customer_id: str, lo: datetime, hi: datetime) -> None:
    """Drawn organic orders timed in [lo, hi) become abandoned carts; their points burn and delivery go too."""
    rows = conn.execute(
        "SELECT id, at, product_id, amount FROM sim_pending_events WHERE drawn = 1 AND kind = 'order' "
        "AND customer_id = ? AND at >= ? AND at < ?",
        (customer_id, _iso(lo), _iso(hi)),
    ).fetchall()
    for row in rows:
        delivered_at = datetime.fromisoformat(row["at"]) + timedelta(days=DELIVERY_DAYS)
        conn.execute(
            "DELETE FROM sim_pending_events WHERE drawn = 1 AND kind = 'points_burned' AND customer_id = ? AND at = ?",
            (customer_id, row["at"]),
        )
        conn.execute(
            "DELETE FROM sim_pending_events WHERE id = (SELECT id FROM sim_pending_events WHERE drawn = 0 "
            "AND kind = 'delivered' AND customer_id = ? AND at = ? AND product_id = ? AND amount = ? LIMIT 1)",
            (customer_id, _iso(delivered_at), row["product_id"], row["amount"]),
        )
        conn.execute(
            "UPDATE sim_pending_events SET kind = 'cart_abandoned', "
            "amount = (SELECT price FROM products WHERE id = product_id) WHERE id = ?",
            (row["id"],),
        )


# --- The hourly steps ----------------------------------------------------------------------------

OFFER_COLUMNS = (
    "o.id, o.code, o.customer_id, o.offer_type, o.category, o.params, o.featured_product_ids, o.send_at, "
    "o.sent_at, o.expires_at, o.status, ch.kind AS chat_kind, ch.chat_id"
)


def _unfated(conn: sqlite3.Connection, now: datetime) -> list[sqlite3.Row]:
    """Unexpired sent Offers to Customers without a chat, and claimed ones of Testers, that have no fate yet."""
    return conn.execute(
        f"SELECT {OFFER_COLUMNS} FROM offers o LEFT JOIN chats ch ON ch.customer_id = o.customer_id "
        "LEFT JOIN sim_offer_fates f ON f.offer_id = o.id "
        "WHERE f.offer_id IS NULL AND o.source != ? AND o.expires_at > ? "
        "AND ((o.status = ? AND ch.kind IS NULL) OR (o.status = ? AND ch.kind = 'tester')) ORDER BY o.id",
        (OfferSource.HISTORY_RANDOM, _iso(now), OfferStatus.SENT, OfferStatus.CLAIMED),
    ).fetchall()


def _claim_due(conn: sqlite3.Connection, now: datetime) -> int:
    rows = conn.execute(
        "SELECT o.id, o.customer_id, o.category, f.claim_at FROM sim_offer_fates f JOIN offers o ON o.id = f.offer_id "
        "WHERE f.claim_at <= ? AND o.status = ? ORDER BY o.id",
        (_iso(now), OfferStatus.SENT),
    ).fetchall()
    for row in rows:
        conn.execute("UPDATE offers SET status = ? WHERE id = ?", (OfferStatus.CLAIMED, row["id"]))
    insert_events(
        conn,
        [
            Event(r["customer_id"], _time(r["claim_at"]), "offer_claimed", r["category"], offer_id=r["id"])
            for r in rows
        ],
    )
    return len(rows)


def _dismiss_due(conn: sqlite3.Connection, now: datetime) -> tuple[int, int]:
    """ "Not now" or Stop at `dismiss_at`. Stop opts the Customer out and withdraws their queued Offers."""
    rows = conn.execute(
        "SELECT o.id, o.customer_id, o.category, f.dismiss_at, f.opts_out FROM sim_offer_fates f "
        "JOIN offers o ON o.id = f.offer_id WHERE f.dismiss_at <= ? AND o.status = ? ORDER BY o.id",
        (_iso(now), OfferStatus.SENT),
    ).fetchall()
    events = []
    for row in rows:
        at = _time(row["dismiss_at"])
        conn.execute("UPDATE offers SET status = ? WHERE id = ?", (OfferStatus.DISMISSED, row["id"]))
        events.append(Event(row["customer_id"], at, "offer_dismissed", row["category"], offer_id=row["id"]))
        if row["opts_out"]:
            conn.execute("UPDATE customers SET opted_out = 1 WHERE id = ?", (row["customer_id"],))
            conn.execute(
                "UPDATE offers SET status = ? WHERE customer_id = ? AND status = ?",
                (OfferStatus.WITHDRAWN, row["customer_id"], OfferStatus.QUEUED),
            )
            events.append(Event(row["customer_id"], at, "opted_out"))
    insert_events(conn, events)
    return len(rows), sum(row["opts_out"] for row in rows)


def _redemptions_due(conn: sqlite3.Connection, now: datetime) -> list[sqlite3.Row]:
    return conn.execute(
        f"SELECT {OFFER_COLUMNS}, f.buy_at FROM sim_offer_fates f JOIN offers o ON o.id = f.offer_id "
        "LEFT JOIN chats ch ON ch.customer_id = o.customer_id "
        f"WHERE f.buys = 1 AND f.buy_at <= ? AND o.status IN ({','.join('?' * len(ACTIVE))}) ORDER BY o.id",
        (_iso(now), *ACTIVE),
    ).fetchall()


def _expire(conn: sqlite3.Connection, now: datetime) -> int:
    """Unredeemed live Offers past `expires_at`. Dismissed and withdrawn ones keep their status; past Offers (T14)
    are settled already."""
    cursor = conn.execute(
        f"UPDATE offers SET status = ? WHERE status IN ({','.join('?' * len(UNREDEEMED))}) "
        "AND expires_at <= ? AND source != ?",
        (OfferStatus.EXPIRED, *UNREDEEMED, _iso(now), OfferSource.HISTORY_RANDOM),
    )
    return cursor.rowcount


def _window(offer: sqlite3.Row, fate: Fate) -> tuple[datetime, datetime]:
    lo = _time(offer["sent_at"]) or _time(offer["send_at"])
    return lo, fate.buy_at if fate.buys else lo + HORIZON


def _between(rng: np.random.Generator, lo: datetime, hi: datetime) -> datetime:
    seconds = int((hi - lo).total_seconds())
    return lo + timedelta(seconds=int(rng.integers(0, seconds))) if seconds > 0 else lo


def _iso(at: datetime | None) -> str | None:
    return at.isoformat(timespec="seconds") if at else None


def _time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
