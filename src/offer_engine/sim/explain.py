"""What Ground Truth says about one Customer's Decision, for the live engine view's truth panel (T40, QnA Q53).

Simulator side (ADR 0002): the pipeline and the trace never call this. The live page shows it in a panel marked
"Hidden from the engine", next to the Estimated Lift the engine used.

Each chance is the 7-day chance of buying at the Customer's base on the Decision's day, as `outcomes.buy_chance`
draws a sent Offer's fate. An option of the Eligible Set is priced at the deepest terms it allowed; the Offer that
went out, at its own terms.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from offer_engine.db import load_catalog
from offer_engine.domain import OfferType
from offer_engine.sim import ground_truth
from offer_engine.sim.world import outcomes


@dataclass(frozen=True)
class Candidate:
    """An option of the Eligible Set at the terms to price it at."""

    offer_type: OfferType
    category: str | None
    params: dict[str, float]


@dataclass(frozen=True)
class TruthOption:
    offer_type: OfferType
    category: str | None
    depth: float
    chance: float
    lift: float  # chance − the no-Offer chance
    chosen: bool = False


@dataclass(frozen=True)
class TruthView:
    customer_id: str
    response_class: str
    at: datetime
    no_offer: float
    options: tuple[TruthOption, ...]


def truth_for(
    conn: sqlite3.Connection,
    customer_id: str,
    offer: sqlite3.Row | None,
    at: datetime,
    candidates: Sequence[Candidate] = (),
) -> TruthView | None:
    """The Response Class, the no-Offer chance and the chance under each candidate at `at`. `offer` (an `offers`
    row) replaces the candidate it was made from, marked chosen. None for a Customer without Ground Truth."""
    customer = outcomes.sim_customer(conn, customer_id)
    if customer is None:
        return None
    catalog = load_catalog(conn)
    base = outcomes.base_chance(customer, at)

    def priced(offer_type: OfferType, row, chosen: bool = False) -> TruthOption:
        """`row` has an Offer's `category`, `params` and `featured_product_ids`, as `buy_chance` reads them."""
        category = catalog.categories[outcomes.redemption_category(row, catalog, customer.traits)]
        depth = ground_truth.offer_depth(offer_type, json.loads(row["params"]), category)
        chance = ground_truth.p_buy(ground_truth.with_base(customer.truth[offer_type], base), depth)
        return TruthOption(offer_type, row["category"], depth, chance, chance - base, chosen)

    chosen = None
    if offer is not None:
        chosen = priced(OfferType(offer["offer_type"]), offer, chosen=True)
    options = []
    for c in candidates:
        if chosen is not None and (c.offer_type, c.category) == (chosen.offer_type, chosen.category):
            options.append(chosen)
            chosen = None
            continue
        row = {"category": c.category, "params": json.dumps(c.params), "featured_product_ids": "[]"}
        options.append(priced(c.offer_type, row))
    if chosen is not None:
        options.append(chosen)
    return TruthView(customer_id, _response_class(conn, customer), at, base, tuple(options))


def _response_class(conn: sqlite3.Connection, customer: outcomes.SimCustomer) -> str:
    row = conn.execute(
        "SELECT response_class FROM sim_response_class WHERE customer_id = ?", (customer.id,)
    ).fetchone()
    return row[0] if row else ground_truth.response_class(list(customer.truth.values()))
