"""`offer-engine demo snapshot` and `demo reset`: save the world for the demo and bring it back (T36)."""

from __future__ import annotations

import argparse
from pathlib import Path

from offer_engine.commands.clock import TIME_FORMAT


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "demo", help="snapshot the world for the demo, or reset it to the snapshot"
    )
    actions = parser.add_subparsers(dest="demo_action", metavar="<action>", required=True)
    snap = actions.add_parser("snapshot", help="copy the database to the demo snapshot")
    snap.add_argument("--path", type=Path, default=None, help="snapshot file (default data/demo.db)")
    snap.set_defaults(func=run_snapshot)
    reset = actions.add_parser("reset", help="copy the demo snapshot back into the database")
    reset.add_argument("--path", type=Path, default=None, help="snapshot file (default data/demo.db)")
    reset.set_defaults(func=run_reset)


def run_snapshot(args: argparse.Namespace) -> int:
    from offer_engine.demo import snapshot

    path = args.path or snapshot.DEFAULT_PATH
    conn = _open()
    snapshot.snapshot(conn, path)
    print(f"Saved the world to {path}: {_describe(conn)}")
    conn.close()
    return 0


def run_reset(args: argparse.Namespace) -> int:
    from offer_engine.demo import snapshot

    path = args.path or snapshot.DEFAULT_PATH
    conn = _open()
    try:
        snapshot.reset(conn, path)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from None
    print(f"Reset the world from {path}: {_describe(conn)}")
    conn.close()
    return 0


def _open():
    from offer_engine.db import connect

    conn = connect()
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'customers'").fetchone():
        conn.close()
        raise SystemExit("no world in the database; run `offer-engine generate` first")
    return conn


def _describe(conn) -> str:
    from offer_engine import clock

    customers = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    return f"{clock.now(conn).strftime(TIME_FORMAT)}, {customers:,} Customers"
