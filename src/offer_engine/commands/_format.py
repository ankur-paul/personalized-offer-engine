"""Shared text for Decisions and Offers in command output."""

from __future__ import annotations

import json
import sqlite3

TIME_FORMAT = "%Y-%m-%d %H:%M"

DECISION_QUERY = (
    "SELECT d.*, o.code, o.offer_type, o.category, o.params, o.send_at, o.expires_at, o.caption,"
    " o.worst_case_cost, o.expected_cost, o.status FROM decisions d LEFT JOIN offers o ON o.id = d.offer_id"
)


def fetch_decisions(
    conn: sqlite3.Connection,
    *,
    last: int | None = None,
    customer_id: str | None = None,
    decision_id: int | None = None,
) -> list[sqlite3.Row]:
    """Decisions joined with their Offers, newest first."""
    where, params = [], []
    if customer_id:
        where.append("d.customer_id = ?")
        params.append(customer_id)
    if decision_id is not None:
        where.append("d.id = ?")
        params.append(decision_id)
    query = DECISION_QUERY + (f" WHERE {' AND '.join(where)}" if where else "") + " ORDER BY d.id DESC"
    if last is not None:
        query += " LIMIT ?"
        params.append(last)
    return conn.execute(query, params).fetchall()


def offer_terms(row: sqlite3.Row) -> str:
    if row["offer_type"] is None:
        return "No Offer"
    params = " ".join(f"{k}={v:g}" for k, v in json.loads(row["params"]).items())
    return " ".join(part for part in (row["offer_type"], row["category"], params) if part)


def decision_summary(row: sqlite3.Row) -> str:
    """`pct_category fashion pct=12 cap=170 · chooser=rules · binding: … · rule v0 · valid`."""
    if row["validation_ok"] is None:
        valid = "nothing to validate"
    else:
        valid = "valid" if row["validation_ok"] else "invalid"
    if row["chooser"] == "fallback" and row["validation_ok"]:
        valid += " (Fallback)"
    binding = row["binding_rule"] or "none"
    return f"{offer_terms(row)} · chooser={row['chooser']} · binding: {binding} · rule v{row['rule_version']} · {valid}"


def decision_details(row: sqlite3.Row) -> list[str]:
    lines = []
    if row["code"]:
        lines.append(
            f"Offer {row['code']} {row['status']} · send {_time(row['send_at'])} · expires {_time(row['expires_at'])}"
            f" · worst ₹{row['worst_case_cost']:,.0f} · expected ₹{row['expected_cost']:,.0f}"
        )
        lines.append(f"caption: {row['caption']}")
    if row["reason"]:
        lines.append(f"reason: {row['reason']}")
    if row["chooser"] == "fallback" and row["agent_output"]:
        lines.append(f"agent's rejected proposal: {row['agent_output']}")
    failures = json.loads(row["validation_failures"])
    if failures:
        lines.append("Validation failures:")
        lines += [f"  {f}" for f in failures]
    return lines


def _time(iso: str) -> str:
    from datetime import datetime

    return datetime.fromisoformat(iso).strftime(TIME_FORMAT)
