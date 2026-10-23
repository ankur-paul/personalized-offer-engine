"""The live world's day-step (PLAN §2.5): `advance` runs the marketplace for every Customer, hour by hour.

When an hour crosses midnight, T13's `simulate_day` draws each Customer's organic events for the whole new day.
They wait in `sim_pending_events` and move into `events` in the hour they happen, so a clock stopped mid-day loses
nothing. Deliveries and returns due on later days wait there too, including those the generated history left.

Hour [t, t + 1h) is processed as of its end: its events are inserted, Offers whose `send_at` has passed are
marked sent, the clock moves to t + 1h, and the hooks run with that `now`, so code reading the clock agrees.

Each Customer's draws use a stream keyed by (seed, Customer ID, day), so two runs from the same state differ only
for Customers whose Offers changed what they did.
"""

from __future__ import annotations

import json
import sqlite3
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import numpy as np

from offer_engine import clock, daily_sweep, triggers
from offer_engine.db import load_catalog
from offer_engine.domain import Catalog, Customer, Event, OfferStatus
from offer_engine.sim.generate import CustomerSim, GenContext
from offer_engine.sim.generate.customers import Traits
from offer_engine.sim.generate.history import POINTS_VALIDITY, insert_events, simulate_day
from offer_engine.sim.world import outcomes
from offer_engine.sim.world.pending import add_pending, pending

DEFAULT_SEED = 7
HOUR = timedelta(hours=1)
ACTIVE = (OfferStatus.SENT, OfferStatus.CLAIMED)
EPOCH = datetime(2000, 1, 1)
OUTCOMES_STREAM = zlib.crc32(b"outcomes")


@dataclass
class DayReport:
    """What one `advance` did. `counts` holds inserted events by kind, `offers_sent`, and the hooks' own counts."""

    start: datetime
    end: datetime
    counts: Counter[str] = field(default_factory=Counter)


@dataclass
class World:
    """The parts of the generated world that don't change while the clock runs."""

    catalog: Catalog
    customers: list[Customer]
    traits: dict[str, Traits]


def advance(conn: sqlite3.Connection, hours: int, rng_seed: int | None = None) -> DayReport:
    """Run `hours` simulated hours from the clock's time, moving the clock one hour at a time."""
    if hours < 0:
        raise ValueError("the Simulation Clock only moves forward")
    seed = DEFAULT_SEED if rng_seed is None else rng_seed
    now = clock.now(conn)
    report = DayReport(now, now + hours * HOUR)
    world: World | None = None
    for _ in range(hours):
        end = now + HOUR
        midnight = datetime.combine(now.date(), time())
        if midnight < now:
            midnight += timedelta(days=1)
        new_events: list[Event] = []
        if midnight < end:
            new_events += release(conn, midnight, report)
            world = world or load_world(conn)
            draw_day(conn, world, midnight.date(), seed)
        new_events += release(conn, end, report)
        report.counts["offers_sent"] += mark_sent(conn, end)
        clock.set_now(conn, end)
        hour_rng = np.random.default_rng([seed, OUTCOMES_STREAM, (end - EPOCH) // HOUR])
        outcomes.on_hour(conn, end, report, hour_rng)
        triggers.on_hour(conn, end, new_events, report)
        daily_sweep.on_hour(conn, end, report)
        now = end
    return report


def load_world(conn: sqlite3.Connection) -> World:
    """Customers with simulator traits, in ID order. Tester copies have none and so do nothing organic."""
    traits: dict[str, Traits] = {}
    customers: list[Customer] = []
    query = (
        "SELECT c.*, t.visit_rate, t.buy_propensity, t.basket_size, t.category_affinity, t.coupon_affinity, "
        "t.churn_hazard FROM customers c JOIN sim_customer_traits t ON t.customer_id = c.id ORDER BY c.id"
    )
    for row in conn.execute(query):
        customers.append(
            Customer(
                id=row["id"],
                signup_at=datetime.fromisoformat(row["signup_at"]),
                city_tier=row["city_tier"],
                device=row["device"],
                channel=row["channel"],
                loyalty_tier=row["loyalty_tier"],
                points_balance=row["points_balance"],
                points_expire_at=_time(row["points_expire_at"]),
            )
        )
        traits[row["id"]] = Traits(
            visit_rate=row["visit_rate"],
            buy_propensity=row["buy_propensity"],
            basket_size=row["basket_size"],
            category_affinity=json.loads(row["category_affinity"]),
            coupon_affinity=row["coupon_affinity"],
            churn_hazard=row["churn_hazard"],
        )
    return World(load_catalog(conn), customers, traits)


def draw_day(conn: sqlite3.Connection, world: World, day: date, seed: int) -> None:
    """Draw every Customer's organic events for `day` into `sim_pending_events`."""
    day_start = datetime.combine(day, time())
    state = load_state(conn)
    due: dict[str, list[Event]] = defaultdict(list)
    for event in pending(conn, drawn=False, before=day_start + timedelta(days=1), delete=True):
        due[event.customer_id].append(event)
    no_orders = {
        row[0]
        for row in conn.execute(
            f"SELECT DISTINCT customer_id FROM offers WHERE status IN ({','.join('?' * len(ACTIVE))}) "
            "AND expires_at > ?",
            (*ACTIVE, _iso(day_start)),
        )
    }

    drawn: list[Event] = []
    later: list[Event] = []
    for customer in world.customers:
        ctx = GenContext(
            conn=None,
            seed=seed,
            n_customers=1,
            start=day,
            end=day,
            catalog=world.catalog,
            customers=[customer],
            traits=world.traits,
            state=state,
            no_order_ids=no_orders,
        )
        ctx.scheduled[day] = due.pop(customer.id, [])
        drawn += simulate_day(ctx, day, customer_rng(seed, customer.id, day))
        for events in ctx.scheduled.values():
            later += events

    add_pending(conn, drawn, drawn=True)
    add_pending(conn, later, drawn=False)
    conn.executemany(
        "UPDATE sim_customer_traits SET churned_at = ? WHERE customer_id = ?",
        [(_iso(sim.churned_at), cid) for cid, sim in state.items() if sim.churned_at],
    )
    conn.commit()


def customer_rng(seed: int, customer_id: str, day: date) -> np.random.Generator:
    return np.random.default_rng([seed, zlib.crc32(customer_id.encode()), day.toordinal()])


def load_state(conn: sqlite3.Connection) -> dict[str, CustomerSim]:
    query = (
        "SELECT c.id, c.points_balance, c.points_expire_at, t.churned_at "
        "FROM customers c JOIN sim_customer_traits t ON t.customer_id = c.id"
    )
    return {
        row["id"]: CustomerSim(
            row["points_balance"], _time(row["points_expire_at"]), _time(row["churned_at"])
        )
        for row in conn.execute(query)
    }


def release(conn: sqlite3.Connection, before: datetime, report: DayReport) -> list[Event]:
    """Move drawn events timed before `before` into `events`, and apply their points to `customers`."""
    events = pending(conn, drawn=True, before=before, delete=True)
    if not events:
        return []
    insert_events(conn, events)
    for event in events:
        if event.kind == "points_earned":
            conn.execute(
                "UPDATE customers SET points_balance = points_balance + ?, points_expire_at = ? WHERE id = ?",
                (int(event.amount), _iso(event.at + POINTS_VALIDITY), event.customer_id),
            )
        elif event.kind == "points_burned":
            conn.execute(
                "UPDATE customers SET points_balance = MAX(0, points_balance - ?) WHERE id = ?",
                (int(event.amount), event.customer_id),
            )
        elif event.kind == "points_expired":
            conn.execute(
                "UPDATE customers SET points_balance = 0, points_expire_at = NULL WHERE id = ?",
                (event.customer_id,),
            )
    conn.commit()
    report.counts.update(event.kind for event in events)
    return events


def mark_sent(conn: sqlite3.Connection, now: datetime) -> int:
    """Queued Offers to Customers without a chat are sent once `send_at` has passed. Chat ones wait for the Offer
    Bot."""
    cursor = conn.execute(
        "UPDATE offers SET status = ? WHERE status = ? AND send_at <= ? "
        "AND customer_id NOT IN (SELECT customer_id FROM chats)",
        (OfferStatus.SENT, OfferStatus.QUEUED, _iso(now)),
    )
    conn.commit()
    return cursor.rowcount


def _iso(at: datetime | None) -> str | None:
    return at.isoformat(timespec="seconds") if at else None


def _time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
