"""The demo scenarios (T37, PLAN "Assumed › Scenarios", QnA Q48): named Decisions with known outcomes.

Each scenario fires one Trigger for its own Customer of the seed-7 world at the snapshot's simulated time. A setup
that changes the Rules or a Customer has a `restore` that undoes it, so the scenarios run in any order with the
same results. The Customers were found on the seed-7 world: the engine treats each as the title claims, with
nothing forced, except where a scenario tampers with the agent's answer (T38).

A step may return lines for the result: the Decision before a Rule change, the preview numbers, the withdraw count.
An `after` step runs once the Decision is made and settled, before `restore`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from offer_engine import pipeline, rules_store
from offer_engine.demo.tamper import tampered
from offer_engine.domain import Chooser, OfferSource, OfferStatus, OfferType, RuleSet, TriggerKind
from offer_engine.offer_bot import responses
from offer_engine.withdraw import withdraw_outstanding

Step = Callable[[sqlite3.Connection, datetime], list[str] | None]
Wrap = Callable[[pipeline.ChooserFn], pipeline.ChooserFn]

SAVING_MARGIN, HARD_LIMITS = "Saving margin", "Hard limits"
SAFETY_NET, MARKETER = "Safety net", "Marketer controls"
# The author of the Rule versions and the withdraw that scenarios make.
DEMO_AUTHOR = "demo"


@dataclass(frozen=True)
class Expect:
    """What the Decision must be for the scenario to pass. `offer_type=None` is No Offer; a None field other than
    `offer_type` isn't checked, for the points where the agent and the rules chooser may disagree. `failure` is the
    start of a Validation failure the Decision must list."""

    offer_type: OfferType | None
    chooser: Chooser | None = None
    binding_rule: str | None = None
    validation_ok: bool | None = None
    failure: str | None = None


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
    wrap_chooser: Wrap | None = None
    after: Step | None = None


# --- Setups ------------------------------------------------------------------------------------


def stop(customer_id: str) -> Step:
    """The Customer's Customer Bot sends /stop."""

    def setup(conn: sqlite3.Connection, now: datetime) -> None:
        responses.stop(conn, _chat_id(conn, customer_id))

    return setup


def restart(customer_id: str) -> Step:
    """The Customer's Customer Bot sends /start."""

    def restore(conn: sqlite3.Connection, now: datetime) -> None:
        responses.restart(conn, _chat_id(conn, customer_id))

    return restore


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


def say(*lines: str) -> Step:
    """A setup that changes nothing and only explains."""
    return lambda conn, now: list(lines)


def tamper(
    *, offer_type: OfferType | None = None, params: dict[str, float] | None = None, caption: str | None = None
) -> Wrap:
    return lambda chooser: tampered(chooser, offer_type=offer_type, params=params, caption=caption)


def rule_change(customer_id: str, change: Callable[[RuleSet], RuleSet], what: str) -> tuple[Step, Step]:
    """A setup and its restore, for a Daily Sweep scenario. The setup decides for the Customer under the current
    Rules and forgets that Decision, previews the change, then saves it as `DEMO_AUTHOR`, so the scenario's own
    Decision runs under the new Rules. The restore saves the original Rules again, as a new version."""
    original: list[int] = []

    def setup(conn: sqlite3.Connection, now: datetime) -> list[str]:
        from offer_engine.demo import runner
        from offer_engine.sim import preview

        version, rules = rules_store.current_rules(conn)
        stages = []
        pipeline.decide(conn, customer_id, TriggerKind.DAILY_SWEEP, now, on_stage=stages.append)
        runner.clear_run(conn, customer_id, now)
        new = change(rules)
        impact = preview.preview(conn, new)
        saved = rules_store.save_rules(conn, new, DEMO_AUTHOR, note=what)
        original.append(version)
        return [
            f"Before, under Rules v{version}: {stages[-1].summary}",
            f"Preview impact on the next Daily Sweep ({impact.at:%d %b %H:%M}): {impact.headline()}",
            f"Saved Rules v{saved} as {DEMO_AUTHOR}: {what}",
        ]

    def restore(conn: sqlite3.Connection, now: datetime) -> list[str]:
        if not original:
            return []
        version = original.pop()
        saved = rules_store.revert(conn, version, DEMO_AUTHOR)
        return [f"Reverted: Rules v{saved}, saved as {DEMO_AUTHOR}, equals v{version}"]

    return setup, restore


def lower_tier_max(tier: str, pct: float) -> Callable[[RuleSet], RuleSet]:
    return lambda rules: replace(rules, max_pct_by_loyalty_tier={**rules.max_pct_by_loyalty_tier, tier: pct})


WITHDRAW_CAPTION = "demo: withdraw setup"
WITHDRAW_OFFERS = (OfferType.FREE_SHIPPING, OfferType.NUDGE)


def queue_offers(customer_id: str) -> Step:
    """Two `queued` live Offers for the Customer, made now, as if two Decisions had just gone out."""

    def setup(conn: sqlite3.Connection, now: datetime) -> list[str]:
        expires = now + timedelta(days=rules_store.current_rules(conn)[1].offer_validity_days)
        made = []
        for i, offer_type in enumerate(WITHDRAW_OFFERS, start=1):
            code = f"DEMO-{customer_id}-W{i}"
            conn.execute(
                "INSERT INTO offers (code, customer_id, offer_type, category, params, created_at, send_at,"
                " expires_at, caption, rule_version, worst_case_cost, expected_cost, status, source)"
                " VALUES (?, ?, ?, NULL, '{}', ?, ?, ?, ?, 0, 0, 0, ?, ?)",
                (
                    code,
                    customer_id,
                    offer_type,
                    _iso(now),
                    _iso(now),
                    _iso(expires),
                    WITHDRAW_CAPTION,
                    OfferStatus.QUEUED,
                    OfferSource.LIVE,
                ),
            )
            made.append(f"{code} {offer_type}")
        conn.commit()
        return [f"Queued {len(made)} Offers for {customer_id}: {', '.join(made)}"]

    return setup


def withdraw_all(customer_id: str) -> Step:
    """Emergency withdraw as `DEMO_AUTHOR`, then the status of each Offer `queue_offers` made."""

    def after(conn: sqlite3.Connection, now: datetime) -> list[str]:
        count = withdraw_outstanding(conn, now, DEMO_AUTHOR)
        rows = conn.execute(
            "SELECT code, status FROM offers WHERE customer_id = ? AND caption = ? ORDER BY id",
            (customer_id, WITHDRAW_CAPTION),
        )
        return [
            f"Emergency withdraw by {DEMO_AUTHOR}: {count} outstanding Offers withdrawn",
            *(f"  {row['code']}: {row['status']}" for row in rows),
        ]

    return after


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="seconds")


# --- The scenarios, in demo order --------------------------------------------------------------

OPTED_OUT = "C09918"  # Persona Card `new_one_order`; gets a ₹0 Nudge when opted in
FATIGUE = "C00005"  # no chat; gets free shipping when not paused
REAL_DISCOUNT = "C01588"  # bronze, no chat: the rules chooser gives 7% off fashion
BREAKS_RULE = "C01377"  # platinum, with a % option on the Daily Sweep; the Fallback gives 6% off fashion
MANIPULATES = "C01835"  # gold; the agent gives free shipping
WITHDRAW = "C00008"  # no chat, not in the Holdout

TAMPERED_PCT = 40.0  # above every loyalty-tier maximum
MANIPULATIVE_CAPTION = "Hurry, 30% off tonight only!"
RULE_CHANGE_SETUP, RULE_CHANGE_RESTORE = rule_change(
    REAL_DISCOUNT, lower_tier_max("bronze", 5.0), "the bronze tier maximum goes from 15% to 5%"
)

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
        customer_id=REAL_DISCOUNT,
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
    Scenario(
        name="agent-breaks-rule",
        title="Validation rejects a rule-breaking proposal; the Fallback decides",
        proves="Whatever the agent proposes, nothing past a Rule goes out: the rules chooser takes over.",
        customer_id=BREAKS_RULE,
        setup=say(f"The agent's answer is tampered to {TAMPERED_PCT:g}% off before Validation sees it."),
        trigger=TriggerKind.DAILY_SWEEP,
        expect=Expect(
            OfferType.PCT_CATEGORY, Chooser.FALLBACK, validation_ok=True, failure="param_out_of_range: pct=40"
        ),
        group=SAFETY_NET,
        wrap_chooser=tamper(
            offer_type=OfferType.PCT_CATEGORY,
            params={"pct": TAMPERED_PCT},
            caption=f"{TAMPERED_PCT:g}% off, just for you.",
        ),
    ),
    Scenario(
        name="manipulative-caption",
        title="The Caption Check blocks invented urgency",
        proves="A caption that pressures the Customer or adds terms never goes out: the Fallback's caption does.",
        customer_id=MANIPULATES,
        setup=say(f'The agent\'s caption is tampered to "{MANIPULATIVE_CAPTION}".'),
        trigger=TriggerKind.DAILY_SWEEP,
        expect=Expect(
            OfferType.FREE_SHIPPING, Chooser.FALLBACK, validation_ok=True, failure="invented_urgency"
        ),
        group=SAFETY_NET,
        wrap_chooser=tamper(caption=MANIPULATIVE_CAPTION),
    ),
    Scenario(
        name="rule-change",
        title="A Rule change flips a Decision",
        proves="A marketer tightens a Rule and the same Customer's Offer changes with it, after a preview of the cost.",
        customer_id=REAL_DISCOUNT,
        setup=RULE_CHANGE_SETUP,
        trigger=TriggerKind.DAILY_SWEEP,
        expect=Expect(OfferType.PCT_CATEGORY, Chooser.RULES, "max_pct_by_loyalty_tier", True),
        group=MARKETER,
        restore=RULE_CHANGE_RESTORE,
    ),
    Scenario(
        name="withdraw",
        title="Emergency withdraw pulls outstanding Offers",
        proves="One click withdraws every outstanding Offer; the frequency cap already stops a third one.",
        customer_id=WITHDRAW,
        setup=queue_offers(WITHDRAW),
        trigger=TriggerKind.DAILY_SWEEP,
        expect=Expect(None, Chooser.RULES, "frequency_cap_count"),
        group=MARKETER,
        after=withdraw_all(WITHDRAW),
    ),
]


def get(name: str) -> Scenario:
    for scenario in SCENARIOS:
        if scenario.name == name:
            return scenario
    raise KeyError(f"no scenario {name!r}; `offer-engine demo list` shows them")
