"""`offer-engine generate`: fill the database with a catalog, Customers and organic history, deterministic for a seed.

Each step reads and extends a shared `GenContext` and writes its own tables. Later tickets append steps to `STEPS`.
"""

from __future__ import annotations

import sqlite3
import zlib
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime

import numpy as np

from offer_engine import clock
from offer_engine.db import migrate
from offer_engine.domain import Catalog, Customer, Event


@dataclass
class CustomerSim:
    """Mutable simulator state for one Customer, carried from day to day."""

    points_balance: int = 0
    points_expire_at: datetime | None = None
    churned_at: datetime | None = None


@dataclass
class GenContext:
    conn: sqlite3.Connection
    seed: int
    n_customers: int
    start: date  # first simulated day of history
    end: date  # day after the last; the Simulation Clock's start date
    catalog: Catalog | None = None
    customers: list[Customer] = field(default_factory=list)
    traits: dict = field(default_factory=dict)  # customer id -> customers.Traits
    state: dict[str, CustomerSim] = field(default_factory=dict)
    # Events due on a later day (deliveries, returns), keyed by day.
    scheduled: dict[date, list[Event]] = field(default_factory=lambda: defaultdict(list))

    def rng(self, name: str) -> np.random.Generator:
        """A stream per step name, so adding a step never shifts another step's draws."""
        return np.random.default_rng([self.seed, zlib.crc32(name.encode())])


from offer_engine.sim.generate import catalog, customers, history

STEPS: list[Callable[[GenContext], None]] = [catalog.step, customers.step, history.step]

# Wiped before every run, children first. Every `sim_*` table is wiped too.
GENERATED_TABLES = ("events", "decisions", "offers", "chats", "customers", "products", "categories")


def history_start(end: date, months: int) -> date:
    month_index = end.year * 12 + end.month - 1 - months
    return date(month_index // 12, month_index % 12 + 1, min(end.day, 28))


def wipe(conn: sqlite3.Connection) -> None:
    query = "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'sim\\_%' ESCAPE '\\'"
    sim_tables = [row[0] for row in conn.execute(query)]
    for table in sorted(sim_tables) + list(GENERATED_TABLES):
        conn.execute(f"DELETE FROM {table}")
    conn.execute("DELETE FROM clock")
    conn.commit()


def run(conn: sqlite3.Connection, n_customers: int, months: int = 12, seed: int = 7) -> GenContext:
    """Wipe generated tables and rebuild the world. History ends at the Simulation Clock's start."""
    migrate(conn)
    wipe(conn)
    end = clock.START.date()
    ctx = GenContext(conn, seed, n_customers, history_start(end, months), end)
    for step in STEPS:
        step(ctx)
        conn.commit()
    return ctx
