"""`offer-engine demo snapshot` and `demo reset`: save the world for the demo and bring it back (T36).
`offer-engine demo list`, `demo run NAME` and `demo check`: the demo scenarios (T37)."""

from __future__ import annotations

import argparse
from pathlib import Path

from offer_engine.commands.clock import TIME_FORMAT


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "demo", help="snapshot or reset the demo world, and run the demo scenarios"
    )
    actions = parser.add_subparsers(dest="demo_action", metavar="<action>", required=True)
    snap = actions.add_parser("snapshot", help="copy the database to the demo snapshot")
    snap.add_argument("--path", type=Path, default=None, help="snapshot file (default data/demo.db)")
    snap.set_defaults(func=run_snapshot)
    reset = actions.add_parser("reset", help="copy the demo snapshot back into the database")
    reset.add_argument("--path", type=Path, default=None, help="snapshot file (default data/demo.db)")
    reset.set_defaults(func=run_reset)
    listing = actions.add_parser("list", help="list the demo scenarios in demo order")
    listing.set_defaults(func=run_list)
    one = actions.add_parser("run", help="run one demo scenario and print its trace, Decision and outcome")
    one.add_argument("name", metavar="NAME")
    one.add_argument("--seed", type=int, default=None, help="outcome seed (default SEED)")
    one.set_defaults(func=run_scenario)
    check = actions.add_parser(
        "check", help="run every scenario on a fresh copy of the snapshot; exit 1 on any FAIL"
    )
    check.add_argument("--path", type=Path, default=None, help="snapshot file (default data/demo.db)")
    check.set_defaults(func=run_check)


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


def run_list(args: argparse.Namespace) -> int:
    from offer_engine.demo.scenarios import SCENARIOS

    group = None
    for scenario in SCENARIOS:
        if scenario.group != group:
            group = scenario.group
            print(f"{group}:")
        print(f"  {scenario.name:<18} {scenario.title} ({scenario.customer_id})")
    return 0


def run_scenario(args: argparse.Namespace) -> int:
    from offer_engine.demo import output, runner, scenarios

    try:
        scenarios.get(args.name)
    except KeyError as exc:
        raise SystemExit(exc.args[0]) from None
    from offer_engine.db import migrate

    conn = _open()
    try:
        migrate(conn)
        result = runner.run(conn, args.name, seed=args.seed)
    finally:
        conn.close()
    print("\n".join(output.result_lines(result)))
    return 0 if result.passed else 1


def run_check(args: argparse.Namespace) -> int:
    from offer_engine.demo import output, runner, snapshot

    try:
        results = runner.check(args.path or snapshot.DEFAULT_PATH)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from None
    for result in results:
        print(output.check_line(result))
    failed = sum(not r.passed for r in results)
    print(f"{len(results) - failed} of {len(results)} scenarios passed")
    return 1 if failed else 0


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
