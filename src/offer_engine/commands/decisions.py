"""`offer-engine decisions --last 10 [--customer ID]`: the Decision log, newest first."""

from __future__ import annotations

import argparse


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("decisions", help="list recent Decisions with their Binding Rules")
    parser.add_argument("--last", type=int, default=10, metavar="N")
    parser.add_argument("--customer", metavar="ID")
    parser.set_defaults(func=run)


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
