"""`offer-engine` entry point. Subcommands are discovered from `offer_engine.commands`; there is no list to edit."""

from __future__ import annotations

import argparse
import importlib
import pkgutil
from collections.abc import Sequence

from offer_engine import commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="offer-engine", description="Personalised Offer Engine")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    for module_info in sorted(pkgutil.iter_modules(commands.__path__), key=lambda m: m.name):
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{commands.__name__}.{module_info.name}")
        module.register(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args) or 0
