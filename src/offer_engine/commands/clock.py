"""`offer-engine clock show` and `clock advance --hours N | --days N`."""

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

    hours = args.hours if args.hours is not None else args.days * 24
    if hours < 0:
        raise SystemExit("the Simulation Clock only moves forward")
    conn = _open()
    print(clock.advance(conn, hours).strftime(TIME_FORMAT))
    conn.close()
    return 0
