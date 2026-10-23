"""`offer-engine lift fit` learns Estimated Lift v1 from the history's random past Offers; `lift show CUSTOMER_ID`
prints the Customer's segment and its Estimated Lift per Offer Type."""

from __future__ import annotations

import argparse

TIME_FORMAT = "%Y-%m-%d %H:%M"
RECENCY_TEXT = {
    "<=30": "ordered ≤30 days ago",
    "31-90": "ordered 31–90 days ago",
    ">90": "no order in 90 days",
}


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("lift", help="fit or inspect Estimated Lift")
    actions = parser.add_subparsers(dest="lift_action", metavar="<action>", required=True)
    fit = actions.add_parser("fit", help="learn Estimated Lift per segment and Offer Type from past Offers")
    fit.set_defaults(func=run_fit)
    show = actions.add_parser("show", help="a Customer's segment and Estimated Lift per Offer Type")
    show.add_argument("customer_id", metavar="CUSTOMER_ID")
    show.set_defaults(func=run_show)


def run_fit(args: argparse.Namespace) -> int:
    from offer_engine.db import connect, migrate
    from offer_engine.lift import segment_lift

    conn = connect()
    migrate(conn)
    if segment_lift.fit(conn) == 0:
        conn.close()
        raise SystemExit("no past Offers to learn from; run `offer-engine generate`")
    totals = conn.execute(
        "SELECT offer_type, past_offers, moments, offer_rate, base_rate, estimated_lift FROM lift_estimates"
        " WHERE loyalty_tier IS NULL ORDER BY offer_type"
    ).fetchall()
    segments, own = conn.execute(
        "SELECT COUNT(*), SUM(1 - from_type_avg) FROM lift_estimates WHERE loyalty_tier IS NOT NULL"
    ).fetchone()
    print(
        f"Fitted Estimated Lift from {sum(r['past_offers'] for r in totals):,} past Offers and"
        f" {totals[0]['moments']:,} no-offer moments"
    )
    print(f"{segments:,} segment × Offer Type estimates, {segments - own:,} of them the Offer Type average\n")
    print(f"{'Offer Type':<20}{'past Offers':>12}{'bought 7d':>11}{'no Offer':>10}{'Estimated Lift':>16}")
    for r in totals:
        print(
            f"  {r['offer_type']:<18}{r['past_offers']:>12,}{r['offer_rate']:>11.1%}{r['base_rate']:>10.1%}"
            f"{r['estimated_lift']:>16.1%}"
        )
    conn.close()
    return 0


def run_show(args: argparse.Namespace) -> int:
    from offer_engine import clock
    from offer_engine.customers import load_customer_state
    from offer_engine.db import connect, migrate
    from offer_engine.lift import segment_lift

    conn = connect()
    migrate(conn)
    now = clock.now(conn)
    try:
        state = load_customer_state(conn, args.customer_id, now)
    except KeyError:
        conn.close()
        raise SystemExit(f"no Customer {args.customer_id}; run `offer-engine generate` first?") from None
    tier, recency, coupon_user = segment_lift.segment_of(state, now)
    rows = conn.execute(
        "SELECT * FROM lift_estimates WHERE loyalty_tier = ? AND recency = ? AND coupon_user = ?"
        " ORDER BY offer_type",
        (tier, recency, int(coupon_user)),
    ).fetchall()
    averages = {
        r["offer_type"]: r
        for r in conn.execute("SELECT * FROM lift_estimates WHERE loyalty_tier IS NULL ORDER BY offer_type")
    }
    conn.close()
    coupon = "coupon user" if coupon_user else "not a coupon user"
    print(f"{args.customer_id} at {now.strftime(TIME_FORMAT)}: {tier} · {RECENCY_TEXT[recency]} · {coupon}")
    if not averages:
        print("No Estimated Lift yet; run `offer-engine lift fit`")
        return 0
    fitted_at = next(iter(averages.values()))["fitted_at"].replace("T", " ")[:16]
    print(f"Estimated Lift fitted at {fitted_at}\n")
    print(
        f"{'Offer Type':<20}{'Estimated Lift':>16}{'past Offers':>13}{'bought 7d':>11}{'no Offer':>10}  source"
    )
    by_type = {r["offer_type"]: r for r in rows}
    for offer_type, average in averages.items():
        r = by_type.get(offer_type)
        if r is None:
            print(
                f"  {offer_type:<18}{average['estimated_lift']:>16.1%}{0:>13}{'–':>11}{'–':>10}  Offer Type average"
            )
            continue
        source = "Offer Type average (under 30 past Offers)" if r["from_type_avg"] else "segment"
        print(
            f"  {offer_type:<18}{r['estimated_lift']:>16.1%}{r['past_offers']:>13,}{_pct(r['offer_rate']):>11}"
            f"{_pct(r['base_rate']):>10}  {source}"
        )
    return 0


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value:.1%}"
