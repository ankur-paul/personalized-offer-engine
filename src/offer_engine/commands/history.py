"""`offer-engine history summary`: the history's random past Offers by Offer Type (send counts, Claim and Redemption
rates, cost and margin per Redemption) and by moment, against the no-offer moments. Reads the simulator's moments
table for the no-offer side; never part of the decision pipeline."""

from __future__ import annotations

import argparse
from collections import defaultdict

# Calibration target 4 (docs/research/ecommerce-benchmarks.md): Redemption per send.
TARGET_4 = {"targeted": (0.015, 0.05), "broadcast": (0.001, 0.01)}

# Whether the Customer ordered in the 7 days from `start`; uses the events (customer_id, at) index.
BOUGHT_IN_7_DAYS = (
    "EXISTS (SELECT 1 FROM events e WHERE e.customer_id = {who} AND e.kind = 'order'"
    " AND e.at >= {start} AND e.at < strftime('%Y-%m-%dT%H:%M:%S', {start}, '+7 days'))"
)


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("history", help="inspect the generated history's past Offers")
    actions = parser.add_subparsers(dest="history_action", metavar="<action>", required=True)
    summary = actions.add_parser("summary", help="past Offers by Offer Type and moment, with their outcomes")
    summary.set_defaults(func=run_summary)


def run_summary(args: argparse.Namespace) -> int:
    from offer_engine.db import connect, migrate

    conn = connect()
    migrate(conn)
    offers = conn.execute(
        "SELECT o.id, o.customer_id, o.offer_type, o.status,"
        f" {BOUGHT_IN_7_DAYS.format(who='o.customer_id', start='o.send_at')} AS bought"
        " FROM offers o WHERE o.source = 'history_random'"
    ).fetchall()
    if not offers:
        conn.close()
        raise SystemExit("no past Offers yet; run `offer-engine generate`")

    claimed, cost, margin = set(), {}, {}
    query = (
        "SELECT e.offer_id, e.kind, e.amount, c.margin_pct FROM events e LEFT JOIN categories c ON c.name = e.category"
        " WHERE e.offer_id IS NOT NULL"
    )
    for offer_id, kind, amount, margin_pct in conn.execute(query):
        if kind == "offer_claimed":
            claimed.add(offer_id)
        elif kind == "offer_redeemed":
            cost[offer_id] = amount
        elif kind == "order":
            margin[offer_id] = amount * margin_pct / 100
    by_type = defaultdict(list)
    for row in offers:
        by_type[row["offer_type"]].append(row)

    print(f"Past Offers: {len(offers):,} sent to {len({r['customer_id'] for r in offers}):,} Customers\n")
    print(
        f"{'Offer Type':<20}{'sent':>8}{'Claim':>8}{'Redemption':>12}{'bought 7d':>11}"
        f"{'cost/Redemption':>17}{'margin after cost':>19}"
    )
    for offer_type, rows in sorted(by_type.items()):
        redeemed = [r["id"] for r in rows if r["status"] == "redeemed"]
        print(
            f"  {offer_type:<18}{len(rows):>8,}{_share(r['id'] in claimed for r in rows):>8}"
            f"{_share(r['status'] == 'redeemed' for r in rows):>12}{_share(r['bought'] for r in rows):>11}"
            f"{_rupees([cost[i] for i in redeemed]):>17}{_rupees([margin[i] - cost[i] for i in redeemed]):>19}"
        )

    status = {r["id"]: r["status"] for r in offers}
    bought = {r["id"]: r["bought"] for r in offers}
    moments = conn.execute(
        "SELECT m.trigger, m.offer_id,"
        f" {BOUGHT_IN_7_DAYS.format(who='m.customer_id', start='m.at')} AS bought"
        " FROM sim_history_moments m"
    ).fetchall()
    by_trigger = defaultdict(list)
    for row in moments:
        by_trigger[row["trigger"]].append(row)
    print(
        f"\n{'Moment':<20}{'moments':>9}{'sent':>8}{'Redemption':>12}{'bought 7d':>11}{'no Offer: bought 7d':>21}"
    )
    redemptions = {"targeted": [], "broadcast": []}
    for trigger, rows in sorted(by_trigger.items()):
        sent = [r["offer_id"] for r in rows if r["offer_id"] is not None]
        redemptions["broadcast" if trigger == "broadcast" else "targeted"] += [
            status[i] == "redeemed" for i in sent
        ]
        print(
            f"  {trigger:<18}{len(rows):>9,}{len(sent):>8,}{_share(status[i] == 'redeemed' for i in sent):>12}"
            f"{_share(bought[i] for i in sent):>11}{_share(r['bought'] for r in rows if r['offer_id'] is None):>21}"
        )

    print("\nRedemption per send vs calibration target 4")
    for group, outcomes in redemptions.items():
        lo, hi = TARGET_4[group]
        rate = sum(outcomes) / len(outcomes) if outcomes else 0.0
        verdict = "ok" if lo <= rate <= hi else "OUTSIDE"
        print(f"  {group:<18}{rate:>8.1%}   {lo:.1%}–{hi:.0%}  {verdict}")
    conn.close()
    return 0


def _share(flags) -> str:
    flags = list(flags)
    return f"{sum(flags) / len(flags):.1%}" if flags else "–"


def _rupees(values: list[float]) -> str:
    return f"₹{sum(values) / len(values):,.0f}" if values else "–"
