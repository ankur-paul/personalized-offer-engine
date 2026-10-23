"""`offer-engine setup`: walk through creating the Telegram bots in BotFather and filling `.env`."""

from __future__ import annotations

import argparse
from pathlib import Path


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("setup", help="create the Telegram bots step by step and fill .env")
    parser.add_argument(
        "--env-file", type=Path, default=Path(".env"), help="env file to fill (default: ./.env)"
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from offer_engine.setup_wizard import ConsoleIO, run_wizard

    try:
        run_wizard(ConsoleIO(), args.env_file)
    except (KeyboardInterrupt, EOFError):
        print("\nSetup stopped. Finished steps are saved; run `offer-engine setup` again to carry on.")
        return 130
    return 0
