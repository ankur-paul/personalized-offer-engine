"""`offer-engine clock show` and `clock advance --hours N | --days N`, which runs the live world (T17)."""

from __future__ import annotations

import argparse

TIME_FORMAT = "%Y-%m-%d %H:%M"


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("clock", help="show or advance the Simulation Clock")
    actions = parser.add_subparsers(dest="clock_action", metavar="<action>", required=True)
    show = actions.add_parser("show", help="print the simulated time")
    show.set_defaults(func=run_show)
    advance = actions.add_parser("advance", help="move the simulated time forward")
    amount = advance.add_mutually_exclusive_group(required=True)
    amount.add_argument("--hours", type=int)
    amount.add_argument("--days", type=int)
    advance.add_argument("--seed", type=int, help="seed for the live world's draws (default 7)")
    advance.set_defaults(func=run_advance)


def _open():
    from offer_engine.db import connect

    conn = connect()
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'clock'").fetchone():
        conn.close()
        raise SystemExit("database not initialised; run `offer-engine db init`")
    return conn


def run_show(args: argparse.Namespace) -> int:
    from offer_engine import clock

    conn = _open()
    print(clock.now(conn).strftime(TIME_FORMAT))
    conn.close()
    return 0


def run_advance(args: argparse.Namespace) -> int:
    from offer_engine import clock
    from offer_engine.sim.world import day_step

    hours = args.hours if args.hours is not None else args.days * 24
    if hours < 0:
        raise SystemExit("the Simulation Clock only moves forward")
    conn = _open()
    report = day_step.advance(conn, hours, args.seed)
    print(clock.now(conn).strftime(TIME_FORMAT))
    print(format_counts(report.counts))
    conn.close()
    return 0


# Event kinds first in funnel order, then anything the hooks count.
COUNT_ORDER = (
    "session",
    "product_view",
    "add_to_cart",
    "cart_abandoned",
    "order",
    "delivered",
    "return",
    "points_earned",
    "points_burned",
    "points_expired",
    "offers_sent",
    "claimed",
    "redeemed",
    "dismissed",
    "opted_out",
    "expired",
    "sweep.offer",
    "sweep.no_offer",
    "sweep.skipped",
)
PLURALS = {"session": "sessions", "product_view": "product_views", "order": "orders", "return": "returns"}


def format_counts(counts) -> str:
    keys = [k for k in COUNT_ORDER if counts.get(k)] + sorted(
        k for k in counts if k not in COUNT_ORDER and counts[k]
    )
    return " · ".join(f"{PLURALS.get(k, k)} {counts[k]:,}" for k in keys) or "nothing happened"
