"""Run a demo scenario: its setup, its Trigger through the pipeline, and a seeded outcome for its Offer (T37).

The outcome follows ADR 0004 as the live world does: Ground Truth's 7-day chance for the Offer, nudged by the
Customer Bot's recorded message fit, then a flip seeded by `SEED` and the scenario name (QnA Q49). The runner
settles its own Offer, so a scenario Offer never reaches Telegram. Offer codes are seeded too, so the Offer Card,
and the Customer Bot's recorded answer to it, are the same on every run.

A rerun first clears the scenario Customer's earlier run at the same simulated time, so clicking a scenario twice
shows the same Decision twice instead of hitting the frequency cap.
"""

from __future__ import annotations

import sqlite3
import tempfile
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from offer_engine import clock, personas, pipeline
from offer_engine.config import load_settings
from offer_engine.db import connect, load_catalog, migrate
from offer_engine.demo import scenarios, snapshot
from offer_engine.demo.scenarios import Expect, Scenario
from offer_engine.domain import Decision, OfferStatus, TriggerKind
from offer_engine.offer_bot import responses
from offer_engine.trace import Stage, StageListener, Trace

PERSONAS_DIR = personas.PERSONAS_DIR


@dataclass(frozen=True)
class ScenarioResult:
    """The Decision, its trace and, when an Offer went out, its seeded outcome. `fit` is None for a Customer
    without a Customer Bot; the outcome fields are all None for No Offer. `reply` is the Customer Bot's message
    and `bot_reply` the Offer Bot's answer to the Claim or "Not now"."""

    scenario: Scenario
    decision: Decision
    trace: Trace
    p_base: float | None
    fit: float | None
    p_used: float | None
    buys: bool | None
    claims: bool | None
    reply: str | None
    bot_reply: str | None
    passed: bool
    mismatches: tuple[str, ...]

    @property
    def offer(self) -> dict[str, Any]:
        """The trace's `offer` stage data: the Offer's terms, code and caption, or No Offer's reason."""
        return self.trace.stages[-1].data


def run(
    conn: sqlite3.Connection, name: str, *, on_stage: StageListener | None = None, seed: int | None = None
) -> ScenarioResult:
    """Run scenario `name` at the clock's current time. `on_stage` gets each trace stage as the pipeline makes it.
    `seed` (default `SEED`) seeds the outcome flip and the Offer code."""
    scenario = scenarios.get(name)
    seed = load_settings().seed if seed is None else seed
    now = clock.now(conn)
    stages: list[Stage] = []

    def listen(stage: Stage) -> None:
        stages.append(stage)
        if on_stage is not None:
            on_stage(stage)

    _clear_earlier_run(conn, scenario.customer_id, now)
    if scenario.setup is not None:
        scenario.setup(conn, now)
    try:
        _record_trigger_event(conn, scenario, now)
        with pipeline.seeded_codes(seed):
            decision = pipeline.decide(conn, scenario.customer_id, scenario.trigger, now, on_stage=listen)
        outcome = _settle(conn, decision.offer_id, name, seed, now) if decision.offer_id else _NO_OUTCOME
    finally:
        if scenario.restore is not None:
            scenario.restore(conn, now)
    trace = Trace(stages)
    mismatches = tuple(_mismatches(scenario.expect, decision, trace))
    return ScenarioResult(scenario, decision, trace, *outcome, passed=not mismatches, mismatches=mismatches)


def check(snapshot_path: Path = snapshot.DEFAULT_PATH) -> list[ScenarioResult]:
    """Every scenario, each on its own fresh copy of the snapshot, in a temp directory beside it."""
    from offer_engine.sim.offline import copy_db

    if not snapshot_path.is_file():
        raise FileNotFoundError(f"no snapshot at {snapshot_path}; run `offer-engine demo snapshot` first")
    results = []
    with tempfile.TemporaryDirectory(dir=snapshot_path.parent, prefix="demo-check-") as tmp:
        for scenario in scenarios.SCENARIOS:
            path = Path(tmp) / f"{scenario.name}.db"
            copy_db(snapshot_path, path)
            conn = connect(path)
            try:
                migrate(conn)
                results.append(run(conn, scenario.name))
            finally:
                conn.close()
                path.unlink()
    return results


def roleplay_agent() -> tuple[Any | None, str | None]:
    """The Customer Bots' role-play client and model, as `customer_sim` builds them."""
    from offer_engine.customer_sim.app import agent_client

    settings = load_settings()
    return agent_client(settings), settings.fast_agent_model


# --- Steps ---------------------------------------------------------------------------------------


def _clear_earlier_run(conn: sqlite3.Connection, customer_id: str, now: datetime) -> None:
    """Remove what an earlier run of a scenario for this Customer wrote at or after `now`. Generated history ends
    before the snapshot's time, so only scenario writes (or a Trigger fired by hand at the same time) go."""
    at = _iso(now)
    offer_ids = [
        row[0]
        for row in conn.execute(
            "SELECT id FROM offers WHERE customer_id = ? AND created_at >= ?", (customer_id, at)
        )
    ]
    marks = ",".join("?" * len(offer_ids))
    with conn:
        conn.execute(
            "DELETE FROM decision_traces WHERE decision_id IN "
            "(SELECT id FROM decisions WHERE customer_id = ? AND at >= ?)",
            (customer_id, at),
        )
        conn.execute("DELETE FROM decisions WHERE customer_id = ? AND at >= ?", (customer_id, at))
        conn.execute("DELETE FROM events WHERE customer_id = ? AND at >= ?", (customer_id, at))
        conn.execute("DELETE FROM trigger_log WHERE customer_id = ? AND at >= ?", (customer_id, at))
        conn.execute(f"DELETE FROM sim_bot_responses WHERE offer_id IN ({marks})", offer_ids)
        conn.execute(f"DELETE FROM sim_offer_fates WHERE offer_id IN ({marks})", offer_ids)
        conn.execute(f"DELETE FROM offers WHERE id IN ({marks})", offer_ids)


def _record_trigger_event(conn: sqlite3.Connection, scenario: Scenario, now: datetime) -> None:
    """A cart-abandoned Trigger needs its abandoned cart, as `offer-engine trigger cart-abandoned` records it."""
    if scenario.trigger != TriggerKind.CART_ABANDONED:
        return
    from offer_engine.commands.trigger import abandoned_product

    product = abandoned_product(conn, scenario.customer_id, now)
    if product is None:
        raise LookupError(f"{scenario.customer_id} has no carted or viewed product to abandon")
    conn.execute(
        "INSERT INTO events (customer_id, at, kind, category, product_id, amount) VALUES (?, ?, ?, ?, ?, ?)",
        (scenario.customer_id, _iso(now), "cart_abandoned", *product[:3]),
    )
    conn.commit()


# (p_base, fit, p_used, buys, claims, reply, bot_reply)
Outcome = tuple[float | None, float | None, float | None, bool | None, bool | None, str | None, str | None]
_NO_OUTCOME: Outcome = (None,) * 7


def _settle(conn: sqlite3.Connection, offer_id: int, name: str, seed: int, now: datetime) -> Outcome:
    """Mark the Offer sent, draw whether the Customer buys, then Claim or say "Not now" through the Offer Bot's
    own handlers. A Customer Bot role-plays (ADR 0004); anyone else gets the plain Ground Truth draw."""
    from offer_engine.customer_sim import roleplay
    from offer_engine.sim.generate.past_offers import HORIZON
    from offer_engine.sim.world import outcomes

    conn.execute(
        "UPDATE offers SET status = ?, sent_at = ? WHERE id = ? AND status = ?",
        (OfferStatus.SENT, _iso(now), offer_id, OfferStatus.QUEUED),
    )
    conn.commit()
    offer = conn.execute(
        "SELECT o.*, ch.kind AS chat_kind, ch.chat_id FROM offers o "
        "LEFT JOIN chats ch ON ch.customer_id = o.customer_id WHERE o.id = ?",
        (offer_id,),
    ).fetchone()
    rng = np.random.default_rng([seed, zlib.crc32(name.encode())])
    if offer["chat_kind"] == "bot":
        path = personas.path_for(offer["customer_id"], PERSONAS_DIR)
        persona = personas.load(path) if path.is_file() else None
        client, model = roleplay_agent()
        if roleplay.react(conn, offer, persona, client, model, rng) is None:
            return _NO_OUTCOME
        row = conn.execute(
            "SELECT p_base, fit, p_used, buys, claims, reply FROM sim_bot_responses WHERE offer_id = ?",
            (offer_id,),
        ).fetchone()
        p_base, fit, p_used, buys, claims, reply = (
            row["p_base"],
            row["fit"],
            row["p_used"],
            bool(row["buys"]),
            bool(row["claims"]),
            row["reply"],
        )
    else:
        fate = outcomes.draw_fate(conn, offer, load_catalog(conn), now, rng)
        if fate is None:
            return _NO_OUTCOME
        outcomes.save_fate(conn, fate)
        sent_at = datetime.fromisoformat(offer["sent_at"])
        outcomes.cancel_orders(conn, offer["customer_id"], sent_at, fate.buy_at or sent_at + HORIZON)
        conn.commit()
        p_base, fit, p_used, buys, reply = fate.p_used, None, fate.p_used, fate.buys, None
        claims = fate.buys or fate.claim_at is not None
    # A Customer without a chat has chat_id None, which `responses` matches to the Offer's own (None) chat.
    act = responses.claim if claims else responses.dismiss
    bot_reply = act(conn, offer["code"], offer["chat_id"])
    return p_base, fit, p_used, buys, claims, reply, bot_reply


def _mismatches(expect: Expect, decision: Decision, trace: Trace) -> list[str]:
    offer_type = trace.stages[-1].data.get("offer_type")
    wanted = None if expect.offer_type is None else str(expect.offer_type)
    out = []
    if offer_type != wanted:
        out.append(f"expected {wanted or 'No Offer'}, got {offer_type or 'No Offer'}")
    if expect.chooser is not None and decision.chooser != expect.chooser:
        out.append(f"expected chooser {expect.chooser}, got {decision.chooser}")
    if expect.binding_rule is not None and decision.binding_rule != expect.binding_rule:
        out.append(f"expected Binding Rule {expect.binding_rule}, got {decision.binding_rule}")
    if expect.validation_ok is not None:
        ok = None if decision.validation is None else decision.validation.ok
        if ok != expect.validation_ok:
            out.append(f"expected Validation ok={expect.validation_ok}, got {ok}")
    return out


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="seconds")
