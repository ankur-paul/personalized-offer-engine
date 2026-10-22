"""`offer-engine generate --customers N --months M --seed S`: wipe and refill the generated world."""

from __future__ import annotations

import argparse

COUNTED_TABLES = ("categories", "products", "customers", "sim_customer_traits", "events")


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("generate", help="generate the catalog, Customers and their history")
    parser.add_argument("--customers", type=int, default=200)
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--seed", type=int, default=7)
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from offer_engine.db import connect
    from offer_engine.sim.generate import run as generate

    if args.customers < 1 or args.months < 1:
        raise SystemExit("--customers and --months must be at least 1")
    conn = connect()
    generate(conn, args.customers, args.months, args.seed)
    print(f"generated with seed {args.seed}: {args.customers} Customers, {args.months} months of history")
    for table in COUNTED_TABLES:
        print(f"  {table:<22}{conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]:>10,}")
    print("events by kind")
    for kind, count in conn.execute("SELECT kind, COUNT(*) FROM events GROUP BY kind ORDER BY COUNT(*) DESC"):
        print(f"  {kind:<22}{count:>10,}")
    conn.close()
    return 0
