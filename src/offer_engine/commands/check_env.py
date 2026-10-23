"""`offer-engine check-env`: report which `.env` keys are set, never their values."""

from __future__ import annotations

import argparse
from pathlib import Path


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("check-env", help="show which .env keys are set (never their values)")
    parser.add_argument("--env-file", type=Path, default=None, help="env file to read (default: ./.env)")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    lines, ok = report(args.env_file)
    for line in lines:
        print(line)
    return 0 if ok else 1


def report(env_file: Path | None = None) -> tuple[list[str], bool]:
    """The check-env lines, and whether every required key is set and the settings load."""
    from offer_engine.config import ENV_KEYS, REQUIRED_KEYS, load_settings, read_env

    values = read_env(env_file)
    width = max(len(key) for key in ENV_KEYS)
    lines = []
    for key in ENV_KEYS:
        state = "set" if key in values else "missing"
        note = " (required)" if key in REQUIRED_KEYS and key not in values else ""
        lines.append(f"{key:<{width}}  {state}{note}")

    ok = all(key in values for key in REQUIRED_KEYS)
    try:
        load_settings(env_file)
    except ValueError as exc:
        lines.append(f"error: {exc}")
        ok = False
    return lines, ok
