"""`offer-engine caption-check "TEXT" --offer-type pct_category --param pct=15 --param cap=300 --category fashion`:
run the Caption Check on one caption and print PASS or each reason.
"""

from __future__ import annotations

import argparse


def register(subparsers: argparse._SubParsersAction) -> None:
    from offer_engine.domain import OfferType

    parser = subparsers.add_parser("caption-check", help="run the Caption Check on a caption for an Offer")
    parser.add_argument("caption", help="the caption text")
    parser.add_argument("--offer-type", required=True, choices=[t.value for t in OfferType])
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        type=_param,
        metavar="NAME=VALUE",
        help="an Offer term; repeatable",
    )
    parser.add_argument("--category", help="the Offer's category (pct_category)")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from offer_engine.caption_check import check
    from offer_engine.domain import Catalog, OfferType, Proposal

    proposal = Proposal(
        offer_type=OfferType(args.offer_type),
        category=args.category,
        params=dict(args.param),
        caption=args.caption,
    )
    reasons = check(args.caption, proposal, Catalog(categories={}, products={}))
    print("\n".join(reasons) or "PASS")
    return 1 if reasons else 0


def _param(raw: str) -> tuple[str, float]:
    name, sep, value = raw.partition("=")
    try:
        if not sep or not name:
            raise ValueError
        return name, float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected NAME=NUMBER, got {raw!r}") from None
