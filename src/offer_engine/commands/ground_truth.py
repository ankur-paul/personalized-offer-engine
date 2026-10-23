"""`offer-engine ground-truth summary`: Response Class shares against calibration target 9, and the mean base and
max Lift per Offer Type. Reads the simulator's hidden tables; never part of the decision pipeline."""

from __future__ import annotations

import argparse


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("ground-truth", help="inspect the hidden Ground Truth")
    actions = parser.add_subparsers(dest="ground_truth_action", metavar="<action>", required=True)
    summary = actions.add_parser("summary", help="Response Class shares and mean Lift per Offer Type")
    summary.set_defaults(func=run_summary)


def run_summary(args: argparse.Namespace) -> int:
    from offer_engine.db import connect, migrate
    from offer_engine.sim.ground_truth import RESPONSE_CLASSES, TARGET_SHARES

    conn = connect()
    migrate(conn)
    counts = dict(
        conn.execute("SELECT response_class, COUNT(*) FROM sim_response_class GROUP BY 1").fetchall()
    )
    total = sum(counts.values())
    if not total:
        conn.close()
        raise SystemExit("no Ground Truth yet; run `offer-engine generate`")

    print(f"Response Class ({total:,} Customers)   share   target 9")
    for name in RESPONSE_CLASSES:
        share = counts.get(name, 0) / total
        lo, hi = TARGET_SHARES[name]
        verdict = "ok" if lo <= share <= hi else "OUTSIDE"
        print(f"  {name:<28}{share:>6.1%}   {lo:.0%}–{hi:.0%}  {verdict}")

    print(f"\n{'Offer Type':<22}{'mean base':>10}{'mean max Lift':>15}{'excl. Sleeping Dogs':>21}")
    query = (
        "SELECT g.offer_type, AVG(g.base), AVG(g.max_lift),"
        " AVG(CASE WHEN r.response_class != 'sleeping_dog' THEN g.max_lift END)"
        " FROM sim_ground_truth g JOIN sim_response_class r USING (customer_id) GROUP BY 1 ORDER BY 1"
    )
    for offer_type, base, max_lift, positive in conn.execute(query):
        print(f"  {offer_type:<20}{base:>10.2%}{max_lift:>15.2%}{positive:>21.2%}")
    conn.close()
    return 0
