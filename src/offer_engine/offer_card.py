"""The Offer Card (ADR 0005): an image of the Offer's terms, drawn by code from the validated Offer."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from offer_engine.domain import Offer, OfferType

WIDTH, HEIGHT = 800, 450
MARGIN = 48
FONT_PATH = Path(__file__).parent / "assets" / "fonts" / "NotoSans-VF.ttf"
BACKGROUND = "#fff8ef"
ACCENT = "#e2582b"
INK = "#1f1f1f"
MUTED = "#5c5c5c"


def format_inr(amount: float) -> str:
    """Whole rupees with Indian digit grouping: 1499 → ₹1,499; 150000 → ₹1,50,000."""
    digits = str(round(amount))
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return "₹" + ",".join(groups + [tail])


def offer_terms(offer: Offer, catalog_names: dict[str, str]) -> list[str]:
    """The term lines, money line first. A Nudge has no money line."""
    params = offer.params
    name = catalog_names.get(offer.category, offer.category.title()) if offer.category else None
    on_category = f" on {name}" if name else ""
    lines: list[str]
    match offer.offer_type:
        case OfferType.PCT_CATEGORY:
            lines = [f"{params['pct']:g}% off {name}" if name else f"{params['pct']:g}% off"]
            if params.get("cap"):
                lines.append(f"Up to {format_inr(params['cap'])} off")
        case OfferType.FLAT_ABOVE_MIN:
            lines = [f"{format_inr(params['amount'])} off orders above {format_inr(params['min_basket'])}"]
        case OfferType.FREE_SHIPPING:
            lines = ["Free shipping"]
        case OfferType.POINTS_MULTIPLIER:
            lines = [f"{params['multiplier']:g}x points{on_category}"]
        case OfferType.NUDGE:
            lines = []
    expires = offer.expires_at
    lines.append(f"Code {offer.code}")
    lines.append(f"Valid until {expires.day} {expires:%b}, {expires:%H:%M}")
    return lines


def _font(size: int, weight: str) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT_PATH), size)
    font.set_variation_by_name(weight)
    return font


def _fitted(draw: ImageDraw.ImageDraw, text: str, size: int, weight: str) -> ImageFont.FreeTypeFont:
    """The largest font up to `size` that fits `text` inside the margins."""
    font = _font(size, weight)
    while size > 16 and draw.textlength(text, font=font) > WIDTH - 2 * MARGIN:
        size -= 2
        font = _font(size, weight)
    return font


def render_offer_card(offer: Offer, catalog_names: dict[str, str]) -> bytes:
    """A PNG drawing exactly `offer_terms`: the first line large, the rest below it."""
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 16, HEIGHT), fill=ACCENT)
    y = MARGIN
    for i, line in enumerate(offer_terms(offer, catalog_names)):
        headline = i == 0
        font = _fitted(draw, line, 60 if headline else 34, "Bold" if headline else "Regular")
        draw.text((MARGIN, y), line, font=font, fill=INK if headline else MUTED)
        y += font.size + (32 if headline else 18)
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
