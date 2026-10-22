"""`offer-engine check-env`: report which `.env` keys are set, never their values."""

from __future__ import annotations

import argparse
from pathlib import Path


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("check-env", help="show which .env keys are set (never their values)")
    parser.add_argument("--env-file", type=Path, default=None, help="env file to read (default: ./.env)")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from offer_engine.config import ENV_KEYS, REQUIRED_KEYS, load_settings, read_env

    values = read_env(args.env_file)
    width = max(len(key) for key in ENV_KEYS)
    for key in ENV_KEYS:
        state = "set" if key in values else "missing"
        note = " (required)" if key in REQUIRED_KEYS and key not in values else ""
        print(f"{key:<{width}}  {state}{note}")

    ok = all(key in values for key in REQUIRED_KEYS)
    try:
        load_settings(args.env_file)
    except ValueError as exc:
        print(f"error: {exc}")
        ok = False
    return 0 if ok else 1
