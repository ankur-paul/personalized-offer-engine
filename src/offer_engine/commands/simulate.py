"""`offer-engine simulate [--policies …] [--days 28] [--sample 500]`: the offline Policy comparison (T26, PLAN §5).
Each Policy runs on its own copy of the database; prints the table and saves it to `sim_policy_results`. Reads the
simulator's hidden tables; never part of the decision pipeline."""

from __future__ import annotations

import argparse
import json
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import UTC, datetime


def register(subparsers: argparse._SubParsersAction) -> None:
    from offer_engine.sim.offline import DEFAULT_DAYS, DEFAULT_SAMPLE
    from offer_engine.sim.policies import POLICIES
    from offer_engine.sim.world.day_step import DEFAULT_SEED

    parser = subparsers.add_parser(
        "simulate", help="compare the Policies offline on Incremental Margin per ₹ of offer spend"
    )
    parser.add_argument(
        "--policies",
        default=",".join(POLICIES),
        help=f"comma-separated, from {', '.join(POLICIES)}; No Offers always runs as the baseline",
    )
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="simulated days per run")
    parser.add_argument(
        "--sample",
        type=int,
        default=DEFAULT_SAMPLE,
        help="Customers in the stratified sample the agent decides for",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--jobs", type=int, default=4, help="Policies run at once, each in its own process")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from offer_engine import clock
    from offer_engine.config import load_settings
    from offer_engine.db import connect, migrate
    from offer_engine.sim.metrics import summarise
    from offer_engine.sim.offline import run_named, stratified_sample
    from offer_engine.sim.policies import POLICIES

    names = [n.strip() for n in args.policies.split(",") if n.strip()]
    unknown = [n for n in names if n not in POLICIES]
    if unknown:
        raise SystemExit(f"unknown Policies: {', '.join(unknown)} (choose from {', '.join(POLICIES)})")
    names = ["no_offers"] + [n for n in POLICIES if n in names and n != "no_offers"]

    db_path = load_settings().db_path
    conn = connect(db_path)
    migrate(conn)
    start = clock.now(conn)
    print(f"Starting from {start:%Y-%m-%d %H:%M} simulated, {args.days} days, seed {args.seed}.")
    sample = stratified_sample(conn, args.sample, args.seed) if args.sample > 0 else []
    conn.close()

    jobs = [(str(db_path), name, args.days, args.seed, sample) for name in names]
    results = {}
    if args.jobs > 1:
        with ProcessPoolExecutor(
            min(args.jobs, len(jobs)), mp_context=multiprocessing.get_context("spawn")
        ) as pool:
            futures = {pool.submit(run_named, job): job[1] for job in jobs}
            for future in as_completed(futures):
                results[futures[future]] = _done(future.result())
    else:
        for job in jobs:
            results[job[1]] = _done(run_named(job))

    baseline = results["no_offers"]
    population = list(baseline.margin)
    rows = []
    for name in names:
        policy, result = POLICIES[name], results[name]
        if not policy.sample_only:
            rows.append((policy.label, summarise(result, baseline, population, "population")))
        if sample:
            rows.append((policy.label, summarise(result, baseline, sample, "sample")))

    _print_table(rows)
    _print_deciles(rows)
    _save(db_path, start, args, rows)
    return 0


def _done(result):
    calls = f", {result.agent_calls} agent calls" if result.agent_calls else ""
    print(f"  {result.policy} done in {result.runtime_seconds:.0f} s{calls}", flush=True)
    return result


HEADER = (
    f"{'Policy':<15}{'Scope':<12}{'Customers':>10}{'Offers':>9}{'Claimed':>9}{'Redeemed':>9}{'Spend':>12}"
    f"{'Incr. Margin':>14}{'per ₹ spend':>13}{'Sure Things':>13}{'Rejected':>10}{'Fallbacks':>10}{'Runtime':>9}"
)


def _print_table(rows) -> None:
    print()
    print(HEADER)
    for label, m in rows:
        per = "—" if m.per_rupee is None else f"{m.per_rupee:+.2f}"
        print(
            f"{label:<15}{m.scope:<12}{m.customers:>10,}{m.offers_sent:>9,}{m.claimed:>9,}{m.redeemed:>9,}"
            f"{_rupees(m.spend):>12}{_rupees(m.incremental_margin, sign=True):>14}{per:>13}"
            f"{_rupees(m.sure_thing_spend):>13}{m.validation_rejections:>10,}{m.fallbacks:>10,}"
            f"{m.runtime_seconds:>8.0f}s"
        )
    print(
        "\nIncr. Margin: margin net of Offer costs minus No Offers' on the same Customers, days and seed. "
        "Sure Things: spend on Customers who buy anyway (Ground Truth)."
    )


def _print_deciles(rows) -> None:
    graded = [(label, m) for label, m in rows if m.lift_deciles]
    if not graded:
        return
    print("\nLift by decile of Estimated Lift: mean Estimated → mean Ground Truth Lift, lowest decile first")
    for label, m in graded:
        cells = "  ".join(f"{d.estimated_lift:.1%}→{d.true_lift:.1%}" for d in m.lift_deciles)
        print(f"{label:<15}{m.scope:<12}{cells}")


def _save(db_path, start, args, rows) -> None:
    from offer_engine.db import connect

    run_at = datetime.now(UTC).isoformat(timespec="seconds")
    conn = connect(db_path)
    with conn:
        conn.executemany(
            "INSERT INTO sim_policy_results (run_at, start_at, days, seed, policy, scope, customers, offers_sent,"
            " claimed, redeemed, spend, incremental_margin, per_rupee, sure_thing_spend, validation_rejections,"
            " fallbacks, lift_deciles, runtime_seconds) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    run_at,
                    start.isoformat(timespec="seconds"),
                    args.days,
                    args.seed,
                    m.policy,
                    m.scope,
                    m.customers,
                    m.offers_sent,
                    m.claimed,
                    m.redeemed,
                    m.spend,
                    m.incremental_margin,
                    m.per_rupee,
                    m.sure_thing_spend,
                    m.validation_rejections,
                    m.fallbacks,
                    json.dumps([asdict(d) for d in m.lift_deciles]),
                    m.runtime_seconds,
                )
                for _, m in rows
            ],
        )
    conn.close()
    print(f"\nSaved {len(rows)} rows to sim_policy_results (run at {run_at}).")


def _rupees(value: float, sign: bool = False) -> str:
    return f"{'+' if sign and value > 0 else '-' if value < 0 else ''}₹{abs(value):,.0f}"
