"""What the console pages read and do, kept apart from Streamlit so it can be tested: the database connection,
Decision log queries returning DataFrames, the clock step behind the Clock page's buttons, and the Rules page's
version history and budget figures."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections import Counter
from dataclasses import fields, replace
from datetime import datetime

import pandas as pd

from offer_engine import clock, rules_store
from offer_engine.budget import budget_state
from offer_engine.commands._format import DECISION_QUERY, offer_terms, validation_text
from offer_engine.commands.clock import COUNT_ORDER
from offer_engine.config import load_settings
from offer_engine.db import connect
from offer_engine.domain import BudgetMode, Chooser, RuleSet, TriggerKind
from offer_engine.sim.world import day_step
from offer_engine.sim.world.day_step import DayReport

TIME_FORMAT = "%Y-%m-%d %H:%M"
DECISION_LIMIT = 500
TRIGGERS = [t.value for t in TriggerKind]
CHOOSERS = [c.value for c in Chooser]
DECISION_COLUMNS = [
    "id",
    "time",
    "customer",
    "trigger",
    "offer",
    "chooser",
    "reason",
    "binding_rule",
    "rule_version",
    "validation",
    "failures",
    "code",
    "status",
    "caption",
    "agent_output",
]

HISTORY_COLUMNS = ["version", "who", "when", "saved", "note", "changed"]

# One step at a time for the whole console process, so auto mode and a button press (or two open tabs) never
# run the day-step at once.
_step_lock = threading.Lock()


def open_db() -> sqlite3.Connection | None:
    """The database at `DB_PATH`, or None when `db init` hasn't run there."""
    conn = connect(load_settings().db_path)
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'clock'").fetchone():
        conn.close()
        return None
    return conn


def sim_time(conn: sqlite3.Connection) -> str:
    return clock.now(conn).strftime(TIME_FORMAT)


def advance(conn: sqlite3.Connection, hours: int) -> DayReport | None:
    """Run the day-step for `hours`. Returns None, without moving the clock, if a step is already running."""
    if not _step_lock.acquire(blocking=False):
        return None
    try:
        return day_step.advance(conn, hours, load_settings().seed)
    finally:
        _step_lock.release()


def counts_frame(counts: Counter[str]) -> pd.DataFrame:
    """A DayReport's non-zero counts, event kinds in funnel order, then the hooks' counts by name."""
    keys = [k for k in COUNT_ORDER if counts.get(k)] + sorted(
        k for k in counts if k not in COUNT_ORDER and counts[k]
    )
    return pd.DataFrame({"what": keys, "count": [counts[k] for k in keys]})


def decisions(
    conn: sqlite3.Connection,
    *,
    customer_id: str | None = None,
    trigger: str | None = None,
    chooser: str | None = None,
    hide_no_offer: bool = True,
    limit: int = DECISION_LIMIT,
) -> pd.DataFrame:
    """Decisions newest first, with their Offers, one row each in DECISION_COLUMNS."""
    where, params = [], []
    if customer_id:
        where.append("d.customer_id = ?")
        params.append(customer_id)
    if trigger:
        where.append("d.trigger = ?")
        params.append(trigger)
    if chooser:
        where.append("d.chooser = ?")
        params.append(chooser)
    if hide_no_offer:
        where.append("d.offer_id IS NOT NULL")
    query = (
        DECISION_QUERY + (f" WHERE {' AND '.join(where)}" if where else "") + " ORDER BY d.id DESC LIMIT ?"
    )
    rows = conn.execute(query, [*params, limit]).fetchall()
    return pd.DataFrame([_decision_row(row) for row in rows], columns=DECISION_COLUMNS)


def _decision_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "time": datetime.fromisoformat(row["at"]).strftime(TIME_FORMAT),
        "customer": row["customer_id"],
        "trigger": row["trigger"],
        "offer": offer_terms(row),
        "chooser": row["chooser"],
        "reason": row["reason"],
        "binding_rule": row["binding_rule"] or "",
        "rule_version": row["rule_version"],
        "validation": validation_text(row),
        "failures": json.loads(row["validation_failures"]),
        "code": row["code"] or "",
        "status": row["status"] or "",
        "caption": row["caption"] or "",
        "agent_output": row["agent_output"] or "",
    }


def changed_fields(old: RuleSet, new: RuleSet) -> list[str]:
    return [f.name for f in fields(RuleSet) if getattr(old, f.name) != getattr(new, f.name)]


def rule_history(conn: sqlite3.Connection) -> pd.DataFrame:
    """Rule versions newest first, ending with version 0 (the defaults), each with the fields it changed from the
    version before it. `when` is simulated time, `saved` wall-clock UTC."""
    rows = [{"version": 0, "who": "", "when": "", "saved": "", "note": "defaults", "changed": ""}]
    previous = RuleSet()
    for v in reversed(rules_store.list_versions(conn)):
        rows.append(
            {
                "version": v.version,
                "who": v.author,
                "when": v.created_at.strftime(TIME_FORMAT),
                "saved": v.saved_at.strftime(TIME_FORMAT) + " UTC",
                "note": v.note,
                "changed": ", ".join(changed_fields(previous, v.rules)) or "(none)",
            }
        )
        previous = v.rules
    return pd.DataFrame(list(reversed(rows)), columns=HISTORY_COLUMNS)


def categories(conn: sqlite3.Connection) -> list[str]:
    return [row[0] for row in conn.execute("SELECT name FROM categories ORDER BY name")]


def worst_case_exposure(conn: sqlite3.Connection, rules: RuleSet) -> float:
    """This week's spend plus every outstanding Offer at worst-case cost: the most the week can cost so far."""
    budget = budget_state(conn, replace(rules, budget_mode=BudgetMode.WORST_CASE), clock.now(conn))
    return budget.spent + budget.reserved
