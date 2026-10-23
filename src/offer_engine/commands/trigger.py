"""`offer-engine trigger cart-abandoned CUSTOMER_ID`: record the event at clock now and run the decision pipeline.

It fires through `triggers.fire`, so a second cart abandoned at the same simulated time is refused."""

from __future__ import annotations

import argparse

KINDS = ("cart-abandoned",)


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("trigger", help="fire a Trigger for a Customer and print the Decision")
    parser.add_argument("kind", choices=KINDS)
    parser.add_argument("customer_id", metavar="CUSTOMER_ID")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from offer_engine import clock, triggers
    from offer_engine.commands._format import decision_details, decision_summary, fetch_decisions
    from offer_engine.db import connect
    from offer_engine.domain import TriggerKind

    conn = connect()
    now = clock.now(conn)
    if conn.execute("SELECT 1 FROM customers WHERE id = ?", (args.customer_id,)).fetchone() is None:
        raise SystemExit(f"no Customer {args.customer_id}; run `offer-engine generate` first?")
    product = abandoned_product(conn, args.customer_id, now)
    if product is None:
        raise SystemExit(
            f"{args.customer_id} has never carted or viewed a product, so there is no cart to abandon"
        )
    at = now.isoformat(timespec="seconds")
    # The event commits with the Decision, or not at all.
    conn.execute(
        "INSERT INTO events (customer_id, at, kind, category, product_id, amount) VALUES (?, ?, ?, ?, ?, ?)",
        (args.customer_id, at, "cart_abandoned", *product[:3]),
    )
    decision = triggers.fire(conn, triggers.Hit(args.customer_id, TriggerKind.CART_ABANDONED, at), now)
    if decision is None:
        conn.rollback()
        raise SystemExit(
            f"{args.customer_id} already abandoned a cart at {now.strftime('%Y-%m-%d %H:%M')}; advance the clock first"
        )
    row = fetch_decisions(conn, decision_id=decision.id)[0]
    print(
        f"{args.customer_id} abandoned a cart with {product[3]} ({product[1]}) at {now.strftime('%Y-%m-%d %H:%M')}"
    )
    print(f"Decision: {decision_summary(row)}")
    for line in decision_details(row):
        print(f"  {line}")
    conn.close()
    return 0


def abandoned_product(conn, customer_id: str, now) -> tuple[str, str, float, str] | None:
    """(category, product id, price, name) of the latest carted product, else the latest viewed one."""
    for kind in ("add_to_cart", "product_view"):
        row = conn.execute(
            "SELECT p.category, p.id, p.price, p.name FROM events e JOIN products p ON p.id = e.product_id"
            " WHERE e.customer_id = ? AND e.kind = ? AND e.at <= ? ORDER BY e.at DESC LIMIT 1",
            (customer_id, kind, now.isoformat(timespec="seconds")),
        ).fetchone()
        if row:
            return row[0], row[1], row[2], row[3]
    return None
