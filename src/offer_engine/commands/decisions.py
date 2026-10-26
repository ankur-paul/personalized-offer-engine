"""`offer-engine decisions --last 10 [--customer ID]`: the Decision log, newest first.
`offer-engine decisions explain ID [--prompt]`: why one Decision came out as it did, one stage per block (T35)."""

from __future__ import annotations

import argparse
import json
import math


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("decisions", help="list recent Decisions with their Binding Rules")
    parser.add_argument("--last", type=int, default=10, metavar="N")
    parser.add_argument("--customer", metavar="ID")
    parser.set_defaults(func=run)
    actions = parser.add_subparsers(dest="action", metavar="{explain}")
    explain = actions.add_parser("explain", help="print one Decision's trace, stage by stage")
    explain.add_argument("decision_id", type=int, metavar="ID")
    explain.add_argument("--prompt", action="store_true", help="also print the agent's full prompt")
    explain.set_defaults(func=run_explain)


def run(args: argparse.Namespace) -> int:
    from datetime import datetime

    from offer_engine.commands._format import TIME_FORMAT, decision_summary, fetch_decisions
    from offer_engine.db import connect

    if args.last < 1:
        raise SystemExit("--last must be at least 1")
    conn = connect()
    rows = fetch_decisions(conn, last=args.last, customer_id=args.customer)
    if not rows:
        print("no Decisions yet")
    for row in rows:
        at = datetime.fromisoformat(row["at"]).strftime(TIME_FORMAT)
        print(f"#{row['id']} {at} {row['customer_id']} {row['trigger']}: {decision_summary(row)}")
    conn.close()
    return 0


def run_explain(args: argparse.Namespace) -> int:
    from offer_engine.commands._format import decision_summary, fetch_decisions
    from offer_engine.db import connect
    from offer_engine.trace import Trace

    conn = connect()
    try:
        rows = fetch_decisions(conn, decision_id=args.decision_id)
        if not rows:
            raise SystemExit(f"no Decision #{args.decision_id}")
        row = rows[0]
        print(f"Decision #{row['id']} · {row['customer_id']} · {decision_summary(row)}")
        stored = conn.execute(
            "SELECT trace FROM decision_traces WHERE decision_id = ?", (args.decision_id,)
        ).fetchone()
    finally:
        conn.close()
    if stored is None:
        print("This Decision has no trace: it was made before traces were kept (T35).")
        return 0
    for stage in Trace.from_json(stored[0]).stages:
        print()
        print(stage.title)
        print(f"  {stage.summary}")
        for line in DETAILS.get(stage.name, _none)(stage.data, args.prompt):
            print(f"  {line}")
    return 0


# --- One stage's detail lines ------------------------------------------------------------------

MARK = {"passed": "✓", "stopped": "✗", "failed": "✗", "not reached": "·"}


def _none(data: dict, prompt: bool) -> list[str]:
    return []


def _checks(data: dict, prompt: bool) -> list[str]:
    return [f"{MARK[i['status']]} {i['name']} ({i['rule']}): {i['detail']}" for i in data["items"]]


def _eligible_set(data: dict, prompt: bool) -> list[str]:
    lines = []
    for i, o in enumerate(data["options"]):
        ranges = ", ".join(
            f"{p} {_range(lo, hi)}" + (f" ({o['binding_rules'][p]})" if p in o["binding_rules"] else "")
            for p, (lo, hi) in o["ranges"].items()
        )
        lift = o["estimated_lift"]
        lift_text = "no Estimated Lift (prior)" if lift is None else f"Estimated Lift {lift:.1%}"
        lines.append(
            f"[{i}] {_name(o)}: {ranges or 'no parameters'}; worst ₹{o['worst_case_cost']:,.0f}; {lift_text}"
        )
    lines += [f"dropped {key} ({rule})" for key, rule in data["dropped"].items()]
    return lines


def _valuation(data: dict, prompt: bool) -> list[str]:
    lines = []
    for i, o in enumerate(data["options"]):
        params = " ".join(f"{k}={v:g}" for k, v in o["params"].items())
        mark = "→" if i == data["best"] and o["value"] > 0 else " "
        lines.append(
            f"{mark} {' '.join(p for p in (_name(o), params) if p)}: Lift {o['lift']:.1%} × ₹{o['margin']:,.0f}"
            f" − {o['redeem_chance']:.0%} × ₹{o['cost_if_redeemed']:,.0f} = ₹{o['value']:,.1f}"
        )
    return lines


def _agent(data: dict, prompt: bool) -> list[str]:
    if "skipped" in data:
        return []
    lines = []
    if data["output"] is not None:
        lines.append(f"answer: {json.dumps(data['output'], ensure_ascii=False)}")
    if data["prompt"] and prompt:
        lines += ["prompt:", *(f"  {line}" for line in data["prompt"].splitlines())]
    elif data["prompt"]:
        lines.append("prompt: (add --prompt to print it)")
    return lines


def _validation(data: dict, prompt: bool) -> list[str]:
    lines = []
    for c in data["checks"]:
        lines.append(f"{MARK[c['status']]} {c['name']}")
        lines += [f"    {f}" for f in c["failures"]]
    return lines


def _fallback(data: dict, prompt: bool) -> list[str]:
    return ["the agent's failures:", *(f"    {f}" for f in data["rejected"])]


def _offer(data: dict, prompt: bool) -> list[str]:
    if data["offer_type"] is None:
        return []
    expires = data["expires_at"].replace("T", " ")[:16]
    return [
        f"Offer {data['code']} · expires {expires} · expected cost ₹{data['expected_cost']:,.0f}",
        f"caption: {data['caption']}",
        f"reason: {data['reason']}",
    ]


DETAILS = {
    "checks": _checks,
    "eligible_set": _eligible_set,
    "valuation": _valuation,
    "agent": _agent,
    "validation": _validation,
    "fallback": _fallback,
    "offer": _offer,
}


def _name(option: dict) -> str:
    return f"{option['offer_type']} {option['category']}" if option["category"] else option["offer_type"]


def _range(lo: float, hi: float | None) -> str:
    if hi is None or (isinstance(hi, float) and math.isinf(hi)):
        return f"{lo:g} or more"
    return f"{lo:g}–{hi:g}"
