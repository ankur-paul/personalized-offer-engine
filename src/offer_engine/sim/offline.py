"""Offline Policy runs (T26; PLAN §5): each Policy runs on its own copy of the database, from the same state and
seed, for `days` simulated days through the live world's day-step, and is then measured. The source database is
only read, except for the agent's cache.

Every Policy decides for every Customer: chats are dropped in the copy, so Customer Bots' Customers are settled by
Ground Truth like the rest, and Tester copies are opted out, so no Policy sends them anything.
"""

from __future__ import annotations

import json
import math
import sqlite3
import tempfile
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from offer_engine import clock, pipeline
from offer_engine.choosers.priors import lift_at, offer_depth
from offer_engine.customers import load_customer_states, population_filter
from offer_engine.db import connect, load_catalog, migrate
from offer_engine.domain import Catalog, EligibleOption, OfferSource, OfferStatus, OfferType
from offer_engine.lift import segment_lift
from offer_engine.sim import ground_truth
from offer_engine.sim.agent_cache import AgentCache
from offer_engine.sim.generate.history import season
from offer_engine.sim.policies import POLICIES, Policy, RunContext
from offer_engine.sim.world import day_step, outcomes

DEFAULT_DAYS = 28
DEFAULT_SAMPLE = 500
AGENT_RETRIES = 3


@dataclass(frozen=True)
class OfferRecord:
    """One Offer the Policy created, as it stood when the run ended."""

    customer_id: str
    offer_type: OfferType
    sent: bool
    claimed: bool
    redeemed: bool
    cost: float  # what its Redemption cost, 0 if not redeemed in the run
    sure_thing: bool  # the Customer's Response Class (Ground Truth)
    estimated_lift: float | None  # Estimated Lift at the Offer's depth, the Customer's segment at the start
    true_lift: float | None  # Ground Truth Lift at the Offer's depth when sent; None if never sent


@dataclass
class PolicyResult:
    policy: str
    start: datetime
    days: int
    seed: int
    margin: dict[str, float]  # population Customer → margin of orders less returns and every Offer cost
    offers: list[OfferRecord] = field(default_factory=list)
    rejections: Counter[str] = field(
        default_factory=Counter
    )  # Customer → Decisions with a Validation failure
    fallbacks: Counter[str] = field(default_factory=Counter)  # Customer → Fallback Decisions
    agent_calls: int = 0
    runtime_seconds: float = 0.0


def run_policy(
    src_db: Path | str,
    policy: Policy | str,
    days: int = DEFAULT_DAYS,
    seed: int = day_step.DEFAULT_SEED,
    customer_ids: list[str] | None = None,
    *,
    client: Any = None,
    model: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> PolicyResult:
    """Run `policy` for `days` simulated days on a copy of `src_db` and measure it. `customer_ids` is the sample
    the Rules + Agent Policy decides for with the agent (`client`, `model`); its answers are cached in `src_db`."""
    policy = POLICIES[policy] if isinstance(policy, str) else policy
    started = time.monotonic()
    src_db = Path(src_db)
    cache_conn = connect(src_db) if policy.needs_agent else None
    try:
        if cache_conn is not None:
            migrate(cache_conn)
        agent = AgentCache(cache_conn, client, model) if cache_conn is not None and model else None
        ctx = RunContext(frozenset(customer_ids or ()), agent)
        factory = policy.chooser_factory(ctx)
        with tempfile.TemporaryDirectory(prefix=".sim-", dir=src_db.parent) as tmp:
            path = Path(tmp) / f"{policy.name}.db"
            copy_db(src_db, path)
            conn = connect(path)
            try:
                # The copy is thrown away, so it needn't survive a crash: commits skip the disk sync (58 → 24 s a day).
                conn.execute("PRAGMA synchronous = OFF")
                migrate(conn)
                prepare(conn)
                start = clock.now(conn)
                prefetch = getattr(factory, "prefetch", None)
                with pipeline.chooser_override(factory, validate=policy.validate, prefetch=prefetch):
                    for day in range(days):
                        day_step.advance(conn, 24, seed)
                        if progress:
                            progress(f"{policy.label}: day {day + 1}/{days}")
                result = measure(conn, policy.name, start, days, seed)
            finally:
                conn.close()
        result.agent_calls = agent.calls if agent else 0
        result.runtime_seconds = time.monotonic() - started
        return result
    finally:
        if cache_conn is not None:
            cache_conn.close()


def copy_db(src: Path, dst: Path) -> None:
    """A consistent copy through SQLite's backup API, safe while the bots write to `src`."""
    source = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    target = sqlite3.connect(dst)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def prepare(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM chats")
    conn.execute("UPDATE customers SET opted_out = 1 WHERE is_tester_copy = 1")
    conn.commit()


# --- Measuring ---------------------------------------------------------------------------------


def measure(conn: sqlite3.Connection, policy: str, start: datetime, days: int, seed: int) -> PolicyResult:
    """Orders and Redemptions in [start, end); Decisions and Offers in (start, end], as the day-step stamps an
    hour's work with its end, so the source's own Decisions at `start` don't count."""
    end = start + timedelta(days=days)
    window = (_iso(start), _iso(end))
    margin = {row[0]: 0.0 for row in conn.execute(f"SELECT id FROM customers WHERE {population_filter()}")}
    query = (
        "SELECT e.customer_id, e.kind, e.amount, c.margin_pct FROM events e LEFT JOIN categories c "
        "ON c.name = e.category WHERE e.at >= ? AND e.at < ? AND e.kind IN ('order', 'return', 'offer_redeemed')"
    )
    for customer_id, kind, amount, margin_pct in conn.execute(query, window):
        if customer_id not in margin or amount is None:
            continue
        if kind == "offer_redeemed":
            margin[customer_id] -= amount
        else:
            sign = 1 if kind == "order" else -1
            margin[customer_id] += sign * amount * (margin_pct or 0.0) / 100

    result = PolicyResult(policy, start, days, seed, margin)
    for customer_id, chooser, failures in conn.execute(
        "SELECT customer_id, chooser, validation_failures FROM decisions WHERE at > ? AND at <= ?", window
    ):
        if json.loads(failures):
            result.rejections[customer_id] += 1
        if chooser == "fallback":
            result.fallbacks[customer_id] += 1
    result.offers = _offers(conn, start, end)
    return result


def _offers(conn: sqlite3.Connection, start: datetime, end: datetime) -> list[OfferRecord]:
    rows = conn.execute(
        f"SELECT {outcomes.OFFER_COLUMNS}, o.redeemed_at, "
        "EXISTS (SELECT 1 FROM events e WHERE e.offer_id = o.id AND e.kind = 'offer_claimed' AND e.at < ?) "
        "AS claimed, (SELECT e.amount FROM events e WHERE e.offer_id = o.id AND e.kind = 'offer_redeemed' "
        "AND e.at < ? LIMIT 1) AS cost, r.response_class FROM offers o "
        "LEFT JOIN chats ch ON ch.customer_id = o.customer_id "
        "LEFT JOIN sim_response_class r ON r.customer_id = o.customer_id "
        "WHERE o.source = ? AND o.created_at > ? AND o.created_at <= ? ORDER BY o.id",
        (_iso(end), _iso(end), OfferSource.LIVE, _iso(start), _iso(end)),
    ).fetchall()
    if not rows:
        return []
    catalog = load_catalog(conn)
    ids = sorted({row["customer_id"] for row in rows})
    estimated = _estimator(conn, ids, start, catalog)
    sims: dict[str, outcomes.SimCustomer | None] = {}
    records = []
    for row in rows:
        cid = row["customer_id"]
        if cid not in sims:
            sims[cid] = outcomes.sim_customer(conn, cid)
        sent_at = _time(row["sent_at"])
        redeemed = row["status"] == OfferStatus.REDEEMED and row["cost"] is not None
        records.append(
            OfferRecord(
                customer_id=cid,
                offer_type=OfferType(row["offer_type"]),
                sent=sent_at is not None and sent_at < end,
                claimed=bool(row["claimed"]),
                redeemed=redeemed,
                cost=float(row["cost"]) if redeemed else 0.0,
                sure_thing=row["response_class"] == "sure_thing",
                estimated_lift=estimated(row),
                true_lift=true_lift(sims[cid], row, catalog, sent_at) if sent_at and sims[cid] else None,
            )
        )
    return records


def true_lift(customer: outcomes.SimCustomer, offer: sqlite3.Row, catalog: Catalog, at: datetime) -> float:
    """Ground Truth's 7-day buying chance with the Offer, minus without it, on `at`'s day."""
    lapsed = customer.churned_at is not None and customer.churned_at < at
    base = ground_truth.organic_weekly_chance(customer.traits, lapsed, math.sqrt(season(at.date())))
    return outcomes.buy_chance(customer, offer, catalog, at) - base


def _estimator(
    conn: sqlite3.Connection, ids: list[str], start: datetime, catalog: Catalog
) -> Callable[[sqlite3.Row], float | None]:
    """Estimated Lift at an Offer's depth, as the rules chooser values it, for the Customer's segment at `start`."""
    fitted = segment_lift.load(conn, start)
    if fitted is None:
        return lambda row: None
    states = load_customer_states(conn, ids, start)
    cats = list(catalog.categories.values())
    avg_basket = sum(c.avg_basket for c in cats) / len(cats)

    def estimate(row: sqlite3.Row) -> float | None:
        state = states.get(row["customer_id"])
        if state is None:
            return None
        offer_type = OfferType(row["offer_type"])
        option = EligibleOption(offer_type, row["category"], {}, {}, worst_case_cost=0.0)
        category = catalog.categories.get(row["category"])
        basket = category.avg_basket if category else avg_basket
        depth = offer_depth(offer_type, json.loads(row["params"]), basket)
        return lift_at(offer_type, depth, fitted.estimate(state, option))

    return estimate


# --- The sample --------------------------------------------------------------------------------


def stratified_sample(conn: sqlite3.Connection, n: int, seed: int) -> list[str]:
    """`n` population Customers, spread over the Estimated Lift v1 segments (T16) in proportion to their sizes
    (largest remainder), chosen at random within each segment."""
    now = clock.now(conn)
    ids = [
        row[0] for row in conn.execute(f"SELECT id FROM customers WHERE {population_filter()} ORDER BY id")
    ]
    if n >= len(ids):
        return ids
    by_segment: dict[tuple, list[str]] = defaultdict(list)
    for cid, state in load_customer_states(conn, ids, now).items():
        by_segment[segment_lift.segment_of(state, now)].append(cid)
    segments = sorted(by_segment, key=str)
    quotas = {s: n * len(by_segment[s]) / len(ids) for s in segments}
    take = {s: math.floor(q) for s, q in quotas.items()}
    for s in sorted(segments, key=lambda s: (take[s] - quotas[s], str(s)))[: n - sum(take.values())]:
        take[s] += 1
    rng = np.random.default_rng(seed)
    sample = []
    for s in segments:
        members = sorted(by_segment[s])
        sample += [members[i] for i in sorted(rng.choice(len(members), take[s], replace=False))]
    return sorted(sample)


# --- Running several Policies in parallel ------------------------------------------------------


def run_named(job: tuple[str, str, int, int, list[str] | None]) -> PolicyResult:
    """`run_policy` for a worker process: (database path, Policy name, days, seed, sample). The agent's client and
    model come from `.env`."""
    src_db, name, days, seed, sample = job
    client = model = None
    if POLICIES[name].needs_agent:
        client, model = agent_client()
    return run_policy(src_db, name, days, seed, sample, client=client, model=model)


def agent_client() -> tuple[Any, str]:
    """The Anthropic client and `FAST_AGENT_MODEL`, with retries: offline runs can wait out a rate limit."""
    import anthropic

    from offer_engine.config import load_settings

    settings = load_settings()
    if not settings.anthropic_api_key or not settings.fast_agent_model:
        raise SystemExit("Rules + Agent needs ANTHROPIC_API_KEY and FAST_AGENT_MODEL in .env")
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=AGENT_RETRIES)
    return client, settings.fast_agent_model


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="seconds")


def _time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
