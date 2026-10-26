"""The demo scenarios (T37, PLAN "Assumed › Scenarios", QnA Q48): named Decisions with known outcomes.

Each scenario fires one Trigger for its own Customer of the seed-7 world at the snapshot's simulated time. A setup
that changes the Rules or a Customer has a `restore` that undoes it, so the scenarios run in any order with the
same results. The Customers were found on the seed-7 world: the engine treats each as the title claims, with
nothing forced. T38 appends its scenarios to `SCENARIOS`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from offer_engine.domain import Chooser, OfferSource, OfferStatus, OfferType, TriggerKind
from offer_engine.offer_bot import responses

Step = Callable[[sqlite3.Connection, datetime], None]

SAVING_MARGIN, HARD_LIMITS = "Saving margin", "Hard limits"


@dataclass(frozen=True)
class Expect:
    """What the Decision must be for the scenario to pass. `offer_type=None` is No Offer; a None field other than
    `offer_type` isn't checked, for the points where the agent and the rules chooser may disagree."""

    offer_type: OfferType | None
    chooser: Chooser | None = None
    binding_rule: str | None = None
    validation_ok: bool | None = None


@dataclass(frozen=True)
class Scenario:
    name: str
    title: str
    proves: str
    customer_id: str
    setup: Step | None
    trigger: TriggerKind
    expect: Expect
    group: str
    restore: Step | None = None


# --- Setups ------------------------------------------------------------------------------------


def stop(customer_id: str) -> Step:
    """The Customer's Customer Bot sends /stop."""
    return lambda conn, now: responses.stop(conn, _chat_id(conn, customer_id))


def restart(customer_id: str) -> Step:
    """The Customer's Customer Bot sends /start."""
    return lambda conn, now: responses.restart(conn, _chat_id(conn, customer_id))


def _chat_id(conn: sqlite3.Connection, customer_id: str) -> int:
    row = conn.execute("SELECT chat_id FROM chats WHERE customer_id = ?", (customer_id,)).fetchone()
    if row is None:
        raise LookupError(f"{customer_id} has no chat; run `offer-engine chats link-showcase`")
    return row[0]


# Three "Not now"s inside the 14-day window, the last one 4 days ago.
NOT_NOW_DAYS_AGO = (12, 8, 4)
NOT_NOW_CAPTION = "demo: fatigue-pause setup"


def three_not_nows(customer_id: str) -> Step:
    """Three dismissed Nudges in the last 14 simulated days, each with its `offer_dismissed` event."""

    def setup(conn: sqlite3.Connection, now: datetime) -> None:
        for days in NOT_NOW_DAYS_AGO:
            at = now - timedelta(days=days)
            cur = conn.execute(
                "INSERT INTO offers (code, customer_id, offer_type, category, params, created_at, send_at,"
                " sent_at, expires_at, caption, rule_version, worst_case_cost, expected_cost, status, source)"
                " VALUES (?, ?, ?, NULL, '{}', ?, ?, ?, ?, ?, 0, 0, 0, ?, ?)",
                (
                    f"DEMO-{customer_id}-{days}",
                    customer_id,
                    OfferType.NUDGE,
                    _iso(at),
                    _iso(at),
                    _iso(at),
                    _iso(at + timedelta(days=3)),
                    NOT_NOW_CAPTION,
                    OfferStatus.DISMISSED,
                    OfferSource.LIVE,
                ),
            )
            conn.execute(
                "INSERT INTO events (customer_id, at, kind, offer_id) VALUES (?, ?, 'offer_dismissed', ?)",
                (customer_id, _iso(at), cur.lastrowid),
            )
        conn.commit()

    return setup


def forget_not_nows(customer_id: str) -> Step:
    """Undo `three_not_nows`."""

    def restore(conn: sqlite3.Connection, now: datetime) -> None:
        ids = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM offers WHERE customer_id = ? AND caption = ?", (customer_id, NOT_NOW_CAPTION)
            )
        ]
        marks = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM events WHERE offer_id IN ({marks})", ids)
        conn.execute(f"DELETE FROM offers WHERE id IN ({marks})", ids)
        conn.commit()

    return restore


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="seconds")


# --- The scenarios, in demo order --------------------------------------------------------------

OPTED_OUT = "C09918"  # Persona Card `new_one_order`; gets a ₹0 Nudge when opted in
FATIGUE = "C00005"  # no chat; gets free shipping when not paused

SCENARIOS: list[Scenario] = [
    Scenario(
        name="sure-thing",
        title="A Sure Thing gets No Offer",
        proves="A Customer who buys anyway gets nothing: any discount would be lost margin.",
        customer_id="C02030",
        setup=None,
        trigger=TriggerKind.DAILY_SWEEP,
        expect=Expect(None),
        group=SAVING_MARGIN,
    ),
    Scenario(
        name="lost-cause-nudge",
        title="A Lost Cause gets a ₹0 Nudge, not a discount",
        proves="A Customer no discount moves gets a free reminder, so no margin goes on a sale that won't happen.",
        customer_id="C09823",
        setup=None,
        trigger=TriggerKind.CART_ABANDONED,
        expect=Expect(OfferType.NUDGE, validation_ok=True),
        group=SAVING_MARGIN,
    ),
    Scenario(
        name="real-discount",
        title="A Customer a discount moves gets one",
        proves="Where a discount adds more margin than it costs, the engine spends it, within the Rules.",
        # A Persuadable with no chat, so the rules chooser decides: 7% off fashion. The agent gives C01377 (the
        # ticket's first pick) a free Nudge on her grocery cart instead.
        customer_id="C01588",
        setup=None,
        trigger=TriggerKind.DAILY_SWEEP,
        expect=Expect(OfferType.PCT_CATEGORY, binding_rule="max_pct_by_loyalty_tier", validation_ok=True),
        group=SAVING_MARGIN,
    ),
    Scenario(
        name="holdout",
        title="A Holdout Customer gets nothing",
        proves="The Holdout group never gets an Offer, so the engine's lift can be measured against it.",
        customer_id="C04770",
        setup=None,
        trigger=TriggerKind.CART_ABANDONED,
        expect=Expect(None, Chooser.RULES, "holdout_pct"),
        group=HARD_LIMITS,
    ),
    Scenario(
        name="opted-out",
        title="Opt-out is absolute",
        proves="A Customer who sent /stop gets nothing, whatever the engine would have offered.",
        customer_id=OPTED_OUT,
        setup=stop(OPTED_OUT),
        trigger=TriggerKind.DAILY_SWEEP,
        expect=Expect(None, Chooser.RULES, "opt_out"),
        group=HARD_LIMITS,
        restore=restart(OPTED_OUT),
    ),
    Scenario(
        name="fatigue-pause",
        title="Three Not nows pause Offers",
        proves='Three "Not now"s in 14 days pause Offers for 14 days, so the engine stops pestering.',
        customer_id=FATIGUE,
        setup=three_not_nows(FATIGUE),
        trigger=TriggerKind.DAILY_SWEEP,
        expect=Expect(None, Chooser.RULES, "fatigue_dismissals"),
        group=HARD_LIMITS,
        restore=forget_not_nows(FATIGUE),
    ),
]


def get(name: str) -> Scenario:
    for scenario in SCENARIOS:
        if scenario.name == name:
            return scenario
    raise KeyError(f"no scenario {name!r}; `offer-engine demo list` shows them")
