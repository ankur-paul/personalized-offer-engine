"""Caption Check: every case in `tests/data/captions.jsonl` (T08, PLAN §3.5 step 3, ADR 0005)."""

import json
from pathlib import Path

import pytest

from offer_engine import cli
from offer_engine.caption_check import MAX_LENGTH, REASON_CODES, check
from offer_engine.domain import Catalog, Category, OfferType, Product, Proposal
from offer_engine.validation import CaptionChecker

CASES_FILE = Path(__file__).parent / "data" / "captions.jsonl"
CASES = [json.loads(line) for line in CASES_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
CATALOG = Catalog(
    categories={
        "fashion": Category("fashion", margin_pct=45.0, avg_basket=1400.0),
        "grocery": Category("grocery", margin_pct=15.0, avg_basket=650.0),
        "electronics": Category("electronics", margin_pct=10.0, avg_basket=7500.0),
        "beauty": Category("beauty", margin_pct=40.0, avg_basket=850.0),
    },
    products={
        p.id: p
        for p in [
            Product("FAS001", "Rangrez Cotton Kurta", "fashion", 899.0),
            Product("FAS013", "Rangrez Silk Saree", "fashion", 2999.0),
            Product("GRO001", "Annapurna Fresh Basmati Rice 5kg", "grocery", 699.0),
            Product("ELE003", "Voltix Power Bank 20000mAh", "electronics", 1299.0),
            Product("BEA004", "Kesari Glow Sunscreen SPF50", "beauty", 399.0),
        ]
    },
)
PCT = Proposal(OfferType.PCT_CATEGORY, "fashion", {"pct": 15.0, "cap": 300.0}, caption="x", reason="r")


def proposal(offer: dict, caption: str) -> Proposal:
    return Proposal(
        offer_type=OfferType(offer["type"]),
        category=offer.get("category"),
        params={k: float(v) for k, v in offer.get("params", {}).items()},
        featured_product_ids=tuple(offer.get("featured", ())),
        caption=caption,
        reason="test",
    )


def codes(reasons: list[str]) -> set[str]:
    return {r.split(":", 1)[0] for r in reasons}


@pytest.mark.parametrize("case", CASES, ids=[c["caption"][:50] or "<blank>" for c in CASES])
def test_case(case):
    reasons = check(case["caption"], proposal(case["offer"], case["caption"]), CATALOG)
    expected = set() if case["expect"] == "pass" else set(case["expect"])
    assert codes(reasons) == expected, reasons


def test_case_file_size_and_coverage():
    bad = [c for c in CASES if c["expect"] != "pass"]
    good = [c for c in CASES if c["expect"] == "pass"]
    assert len(bad) >= 40
    assert len(good) >= 15
    assert {code for c in bad for code in c["expect"]} == set(REASON_CODES)
    assert all(set(c["expect"]) <= set(REASON_CODES) for c in bad)


def test_each_reason_is_code_then_detail():
    reasons = check("Hurry, 30% off tonight only!", PCT, CATALOG)
    assert [r.split(":", 1)[0] for r in reasons] == [
        "number_mismatch",
        "deadline_mismatch",
        "invented_urgency",
    ]
    assert reasons[0] == "number_mismatch: 30%"
    assert all(r.split(": ", 1)[1] for r in reasons)


def test_length_limit_is_inclusive():
    body = "15% off fashion. "
    at_limit = (body * 30)[:MAX_LENGTH]
    assert len(at_limit) == MAX_LENGTH
    assert check(at_limit, PCT, CATALOG) == []
    assert codes(check(at_limit + "x", PCT, CATALOG)) == {"too_long"}


def test_validity_days_come_from_the_rules():
    caption = "15% off fashion for 5 days"
    assert codes(check(caption, PCT, CATALOG)) == {"number_mismatch"}
    assert check(caption, PCT, CATALOG, validity_days=5) == []


def test_digits_in_a_product_name_pass_only_when_it_is_featured():
    caption = "Your Annapurna Fresh Basmati Rice 5kg is still in your cart."
    nudge = Proposal(OfferType.NUDGE, caption=caption, reason="r")
    assert codes(check(caption, nudge, CATALOG)) == {"number_mismatch"}
    featured = Proposal(OfferType.NUDGE, featured_product_ids=("GRO001",), caption=caption, reason="r")
    assert check(caption, featured, CATALOG) == []


def test_free_delivery_is_fine_only_for_free_shipping():
    caption = "Free delivery on your next order"
    assert check(caption, Proposal(OfferType.FREE_SHIPPING, caption=caption, reason="r"), CATALOG) == []
    assert codes(check(caption, PCT, CATALOG)) == {"unoffered_promise"}


def test_check_fits_validation_caption_checker():
    checker: CaptionChecker = check
    assert checker("15% off fashion", PCT, CATALOG) == []


def test_cli_prints_each_reason(capsys):
    argv = [
        "caption-check",
        "Hurry, 30% off tonight only!",
        "--offer-type", "pct_category",
        "--param", "pct=15",
        "--param", "cap=300",
        "--category", "fashion",
    ]  # fmt: skip
    assert cli.main(argv) == 1
    lines = capsys.readouterr().out.splitlines()
    assert [line.split(":", 1)[0] for line in lines] == [
        "number_mismatch",
        "deadline_mismatch",
        "invented_urgency",
    ]


def test_cli_prints_pass(capsys):
    argv = ["caption-check", "Earn 2x points", "--offer-type", "points_multiplier", "--param", "multiplier=2"]
    assert cli.main(argv) == 0
    assert capsys.readouterr().out.strip() == "PASS"


def test_cli_rejects_a_malformed_param():
    with pytest.raises(SystemExit):
        cli.main(["caption-check", "hi", "--offer-type", "nudge", "--param", "pct"])
