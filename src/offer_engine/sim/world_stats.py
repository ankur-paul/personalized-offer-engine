"""What the live world has done since the clock start, for the live view's world charts (T41; QnA Q54): Decisions
per simulated day by kind, the funnel against the Holdout, Offers by hidden Response Class, and who decided. One
JSON-ready dict, so any page can draw it. Tester copies are left out, except in the list of chat-attached Customers.
Reads Ground Truth's Response Class, so it belongs to the simulator side.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from typing import Any

from offer_engine import clock, personas
from offer_engine.customers import population_filter
from offer_engine.domain import OfferSource, OfferType, RuleSet
from offer_engine.sim.ground_truth import RESPONSE_CLASSES
from offer_engine.sim.live_metrics import funnel, holdout_comparison

# A day's Decisions in five groups, in chart order. A No Offer without a Binding Rule is a chooser's choice: no
# option was worth its cost.
GROUPS = ("paid", "nudge", "nothing", "frequency_cap", "other_rules")
NO_RULE = "none"
_TESTER_SUFFIX = re.compile(r"-t\d+$")


def world_stats(
    conn: sqlite3.Connection, now: datetime, rules: RuleSet, since: datetime = clock.START
) -> dict:
    f = funnel(conn, since)
    holdout = holdout_comparison(conn, rules.holdout_pct, since)
    return {
        "time": now.isoformat(timespec="minutes"),
        "since": since.isoformat(timespec="minutes"),
        "days": decisions_by_day(conn, since),
        "funnel": {
            "sent": f.sent,
            "claimed": f.claimed,
            "redeemed": f.redeemed,
            "spend": round(f.spend, 2),
            "sure_thing_spend": round(f.sure_thing_spend, 2),
        },
        "holdout": {
            "pct": rules.holdout_pct,
            "treated": {"customers": holdout.treated.customers, "orders": holdout.treated.orders},
            "holdout": {"customers": holdout.holdout.customers, "orders": holdout.holdout.orders},
        },
        "truth": by_response_class(conn, since),
        "choosers": choosers(conn, since),
        "chats": chat_customers(conn),
    }


def group_of(offer_type: str | None, binding_rule: str | None) -> str:
    if offer_type == OfferType.NUDGE:
        return "nudge"
    if offer_type is not None:
        return "paid"
    if binding_rule is None:
        return "nothing"
    return "frequency_cap" if binding_rule == "frequency_cap_count" else "other_rules"


def decisions_by_day(conn: sqlite3.Connection, since: datetime = clock.START) -> list[dict[str, Any]]:
    """One entry per simulated day with a Decision: counts per group, per Offer Type and per No Offer Binding Rule."""
    days: dict[str, dict[str, Any]] = {}
    rows = conn.execute(
        "SELECT substr(d.at, 1, 10), o.offer_type, d.binding_rule, COUNT(*) FROM decisions d"
        " JOIN customers c ON c.id = d.customer_id LEFT JOIN offers o ON o.id = d.offer_id"
        f" WHERE d.at >= ? AND {population_filter('c')} GROUP BY 1, 2, 3 ORDER BY 1",
        (_iso(since),),
    )
    for day, offer_type, binding_rule, n in rows:
        entry = days.setdefault(
            day, {"day": day, "groups": dict.fromkeys(GROUPS, 0), "offers": {}, "no_offer": {}}
        )
        entry["groups"][group_of(offer_type, binding_rule)] += n
        detail, key = (
            (entry["offers"], offer_type) if offer_type else (entry["no_offer"], binding_rule or NO_RULE)
        )
        detail[key] = detail.get(key, 0) + n
    return list(days.values())


def by_response_class(conn: sqlite3.Connection, since: datetime = clock.START) -> list[dict[str, Any]]:
    """Per Response Class: its Customers, the live Offers the engine chose for them (paid and Nudges) and what their
    Redemptions cost."""
    stats = {
        rc: {"response_class": rc, "customers": 0, "paid": 0, "nudges": 0, "spend": 0.0}
        for rc in RESPONSE_CLASSES
    }
    for rc, n in conn.execute(
        "SELECT rc.response_class, COUNT(*) FROM customers c JOIN sim_response_class rc ON rc.customer_id = c.id"
        f" WHERE {population_filter('c')} GROUP BY 1"
    ):
        stats[rc]["customers"] = n
    for rc, paid, nudges in conn.execute(
        "SELECT rc.response_class, SUM(o.offer_type != ?), SUM(o.offer_type = ?) FROM offers o"
        " JOIN customers c ON c.id = o.customer_id JOIN sim_response_class rc ON rc.customer_id = o.customer_id"
        f" WHERE o.source = ? AND o.created_at >= ? AND {population_filter('c')} GROUP BY 1",
        (OfferType.NUDGE, OfferType.NUDGE, OfferSource.LIVE, _iso(since)),
    ):
        stats[rc]["paid"], stats[rc]["nudges"] = paid or 0, nudges or 0
    for rc, spend in conn.execute(
        "SELECT rc.response_class, SUM(e.amount) FROM events e JOIN offers o ON o.id = e.offer_id"
        " JOIN customers c ON c.id = o.customer_id JOIN sim_response_class rc ON rc.customer_id = o.customer_id"
        f" WHERE e.kind = 'offer_redeemed' AND o.source = ? AND o.created_at >= ? AND {population_filter('c')}"
        " GROUP BY 1",
        (OfferSource.LIVE, _iso(since)),
    ):
        stats[rc]["spend"] = round(spend or 0.0, 2)
    return list(stats.values())


def choosers(conn: sqlite3.Connection, since: datetime = clock.START) -> dict[str, int]:
    return dict(
        conn.execute(
            "SELECT d.chooser, COUNT(*) FROM decisions d JOIN customers c ON c.id = d.customer_id"
            f" WHERE d.at >= ? AND {population_filter('c')} GROUP BY 1 ORDER BY 1",
            (_iso(since),),
        ).fetchall()
    )


def chat_customers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Each chat-attached Customer (Customer Bots and Testers' copies) with its Decisions, Offers and latest Decision."""
    cards = {card.customer_id: card for card in personas.load_all()}
    chats = conn.execute(
        "SELECT ch.customer_id, ch.kind, c.opted_out FROM chats ch JOIN customers c ON c.id = ch.customer_id ORDER BY 1"
    ).fetchall()
    # `decisions` has no index on customer_id, so read the few chat Customers' Decisions in one pass, oldest first.
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    latest: dict[str, sqlite3.Row] = {}
    for row in conn.execute(
        "SELECT d.customer_id, d.at, d.chooser, d.binding_rule, d.offer_id, o.offer_type, o.category, o.params"
        " FROM decisions d LEFT JOIN offers o ON o.id = d.offer_id"
        f" WHERE d.customer_id IN ({','.join('?' * len(chats))}) ORDER BY d.id",
        [cid for cid, _, _ in chats],
    ):
        counts[row["customer_id"]][0] += 1
        counts[row["customer_id"]][1] += row["offer_id"] is not None
        latest[row["customer_id"]] = row
    out = []
    for cid, kind, opted_out in chats:
        card = cards.get(_TESTER_SUFFIX.sub("", cid))
        row = latest.get(cid)
        out.append(
            {
                "customer_id": cid,
                "kind": kind,
                "name": card.name if card else None,
                "case": personas.CASE_LABELS.get(card.case, card.case) if card else None,
                "opted_out": bool(opted_out),
                "decisions": counts[cid][0],
                "offers": counts[cid][1],
                "latest": None
                if row is None
                else {
                    "at": row["at"],
                    "chooser": row["chooser"],
                    "binding_rule": row["binding_rule"],
                    "offer_type": row["offer_type"],
                    "category": row["category"],
                    "params": json.loads(row["params"]) if row["params"] else {},
                },
            }
        )
    return out


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="seconds")
