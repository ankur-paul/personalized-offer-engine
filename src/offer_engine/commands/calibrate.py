"""`offer-engine calibrate [--strict]`: the generated history against the calibration targets, pass/fail per metric.
Reads the simulator's hidden tables; never part of the decision pipeline."""

from __future__ import annotations

import argparse


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "calibrate", help="check the generated history against the calibration targets"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 if any metric other than a category split misses its target",
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from offer_engine.db import connect, migrate
    from offer_engine.sim.calibration import measure

    conn = connect()
    migrate(conn)
    metrics = measure(conn)
    conn.close()
    if not metrics:
        raise SystemExit("no history yet; run `offer-engine generate`")

    print(f"{'#':<4}{'Metric':<58}{'value':>9}  {'target':<15}")
    for m in metrics:
        verdict = "ok" if m.passed else ("miss (category split)" if m.split else "MISS")
        print(f"{m.id:<4}{m.name:<58}{_fmt(m.value, m.unit):>9}  {_range(m):<15}{verdict}")
    misses = [m for m in metrics if not m.passed and not m.split]
    splits = [m for m in metrics if not m.passed and m.split]
    print(
        f"\n{len(metrics) - len(misses) - len(splits)} of {len(metrics)} on target · {len(misses)} misses"
        f" · {len(splits)} category splits off target (judgement, never fail --strict)"
    )
    return 1 if args.strict and misses else 0


def _fmt(value: float, unit: str) -> str:
    return f"{value:.1%}" if unit == "%" else f"{value:.1f}"


def _range(m) -> str:
    return f"{_fmt(m.lo, m.unit)}–{_fmt(m.hi, m.unit)}"
