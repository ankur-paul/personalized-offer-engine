"""`offer-engine db init`: create or update the database schema."""

from __future__ import annotations

import argparse


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("db", help="database setup")
    actions = parser.add_subparsers(dest="db_action", metavar="<action>", required=True)
    init = actions.add_parser("init", help="create the database or apply new schema files")
    init.set_defaults(func=run_init)


def run_init(args: argparse.Namespace) -> int:
    from offer_engine.config import load_settings
    from offer_engine.db import connect, migrate

    path = load_settings().db_path
    conn = connect(path)
    applied = migrate(conn)
    conn.close()
    print(f"{path}: applied {', '.join(applied)}" if applied else f"{path}: schema up to date")
    return 0
