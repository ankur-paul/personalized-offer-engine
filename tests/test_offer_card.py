from datetime import datetime
from io import BytesIO

import pytest
from PIL import Image

from offer_engine.domain import Offer, OfferSource, OfferStatus, OfferType
from offer_engine.offer_card import HEIGHT, WIDTH, format_inr, offer_terms, render_offer_card

NAMES = {"fashion": "Fashion", "beauty": "Beauty", "home_kitchen": "Home & Kitchen"}
EXPIRES = datetime(2026, 12, 4, 10, 0)
TAIL = ["Code POE-7K3Q9X", "Valid until 4 Dec, 10:00"]


def make_offer(offer_type: OfferType, category: str | None = None, **params: float) -> Offer:
    return Offer(
        id=1,
        code="POE-7K3Q9X",
        customer_id="C00001",
        offer_type=offer_type,
        category=category,
        params=params,
        featured_product_ids=(),
        created_at=datetime(2026, 12, 1, 10, 0),
        send_at=datetime(2026, 12, 1, 10, 0),
        expires_at=EXPIRES,
        caption="",
        rule_version=0,
        worst_case_cost=0.0,
        expected_cost=0.0,
        status=OfferStatus.QUEUED,
        source=OfferSource.LIVE,
    )


ALL_TYPES = [
    (make_offer(OfferType.PCT_CATEGORY, "fashion", pct=15, cap=300), ["15% off Fashion", "Up to ₹300 off"]),
    (make_offer(OfferType.FLAT_ABOVE_MIN, amount=200, min_basket=1499), ["₹200 off orders above ₹1,499"]),
    (make_offer(OfferType.FREE_SHIPPING), ["Free shipping"]),
    (make_offer(OfferType.POINTS_MULTIPLIER, "beauty", multiplier=2), ["2x points on Beauty"]),
    (make_offer(OfferType.NUDGE, "fashion"), []),
]


@pytest.mark.parametrize(("offer", "money_lines"), ALL_TYPES, ids=lambda v: getattr(v, "offer_type", ""))
def test_offer_terms_for_every_offer_type(offer, money_lines):
    assert offer_terms(offer, NAMES) == money_lines + TAIL


def test_every_offer_type_is_covered():
    assert {offer.offer_type for offer, _ in ALL_TYPES} == set(OfferType)


def test_pct_without_cap_has_no_cap_line():
    assert offer_terms(make_offer(OfferType.PCT_CATEGORY, "fashion", pct=12.5), NAMES)[:2] == [
        "12.5% off Fashion",
        "Code POE-7K3Q9X",
    ]


def test_unknown_category_falls_back_to_title_case():
    assert (
        offer_terms(make_offer(OfferType.POINTS_MULTIPLIER, "toys", multiplier=1.5), {})[0]
        == "1.5x points on Toys"
    )


@pytest.mark.parametrize(
    ("amount", "text"),
    [
        (0, "₹0"),
        (40, "₹40"),
        (999, "₹999"),
        (1499, "₹1,499"),
        (150000, "₹1,50,000"),
        (12345678, "₹1,23,45,678"),
    ],
)
def test_format_inr_uses_indian_grouping(amount, text):
    assert format_inr(amount) == text


@pytest.mark.parametrize(("offer", "money_lines"), ALL_TYPES, ids=lambda v: getattr(v, "offer_type", ""))
def test_card_is_a_png_of_the_expected_size(offer, money_lines):
    image = Image.open(BytesIO(render_offer_card(offer, NAMES)))
    assert image.format == "PNG"
    assert image.size == (WIDTH, HEIGHT) == (800, 450)


def test_nudge_card_has_no_rupee_line():
    assert not any("₹" in line for line in offer_terms(make_offer(OfferType.NUDGE), NAMES))


def test_long_terms_still_render():
    offer = make_offer(OfferType.PCT_CATEGORY, "x", pct=15, cap=300)
    render_offer_card(offer, {"x": "Very Long Category Name " * 4})
