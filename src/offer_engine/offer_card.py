"""The Offer Card (ADR 0005): an image of the Offer's terms, drawn by code from the validated Offer."""

from __future__ import annotations

import math
import random
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont

from offer_engine.domain import Offer, OfferType

WIDTH, HEIGHT = 800, 450
SCALE = 2  # drawn at 2x, then shrunk, so edges come out smooth
FONT_PATH = Path(__file__).parent / "assets" / "fonts" / "NotoSans-VF.ttf"

# Layout, in output pixels. The card is a ticket: a colourful body, a perforation, a cream stub.
INSET = 20
RADIUS = 28
PERFORATION_X = 572
NOTCH = 17
BODY_LEFT, BODY_RIGHT = 64, 548
STUB_LEFT, STUB_RIGHT = PERFORATION_X + 26, WIDTH - INSET - 26

OUTER = "#1d1530"
OUTER_DOT = "#2c2147"
STUB = "#fff4e0"
INK = "#1d1530"
MUTED = "#8a7a6a"
GOLD = "#ffd166"
WHITE = "#ffffff"

# Gradient start, end and glow per Offer Type, so each kind of Offer is recognisable at a glance.
THEMES: dict[OfferType, tuple[str, str, str]] = {
    OfferType.PCT_CATEGORY: ("#ff8a1e", "#e0157a", "#ffd166"),
    OfferType.FLAT_ABOVE_MIN: ("#00b386", "#075e7a", "#b8f5c9"),
    OfferType.FREE_SHIPPING: ("#2f6bff", "#08b5d4", "#bde9ff"),
    OfferType.POINTS_MULTIPLIER: ("#7b3ff2", "#e0157a", "#ffd166"),
    OfferType.NUDGE: ("#3b2fb8", "#a13ad6", "#f5c2ff"),
}


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


def _s(value: float) -> int:
    """Output pixels to drawing pixels."""
    return round(value * SCALE)


@lru_cache(maxsize=128)
def _font(size: float, weight: str) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT_PATH), _s(size))
    font.set_variation_by_name(weight)
    return font


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and draw.textlength(f"{lines[-1]} {word}", font=font) <= width:
            lines[-1] += f" {word}"
        else:
            lines.append(word)
    return lines


def _fitted_lines(
    draw: ImageDraw.ImageDraw, text: str, size: int, width: int, max_lines: int
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """The largest bold font up to `size` that wraps `text` into at most `max_lines` lines of `width`."""
    while True:
        font = _font(size, "Bold")
        lines = _wrap(draw, text, font, _s(width))
        fits = len(lines) <= max_lines and all(
            draw.textlength(line, font=font) <= _s(width) for line in lines
        )
        if fits or size <= 22:
            return font, lines
        size -= 2


def _fitted(
    draw: ImageDraw.ImageDraw, text: str, size: int, weight: str, width: int
) -> ImageFont.FreeTypeFont:
    """The largest font up to `size` that fits `text` on one line of `width`."""
    font = _font(size, weight)
    while size > 12 and draw.textlength(text, font=font) > _s(width):
        size -= 1
        font = _font(size, weight)
    return font


@lru_cache(maxsize=len(THEMES))
def _gradient(start: str, end: str, glow: str) -> Image.Image:
    """A diagonal `start`→`end` wash with a soft `glow` in the top-left corner. Smooth, so drawn at 1x."""
    y, x = np.mgrid[0:HEIGHT, 0:WIDTH].astype(np.float32)
    t = ((x / WIDTH + y / HEIGHT) / 2)[..., None]
    rgb = (1 - t) * _rgb(start) + t * _rgb(end)
    halo = np.clip(1 - np.hypot(x - 80, y - 40) / 380, 0, 1)[..., None] ** 2 * 0.45
    rgb = (1 - halo) * rgb + halo * _rgb(glow)
    small = Image.fromarray(rgb.astype(np.uint8), "RGB").convert("RGBA")
    return small.resize((_s(WIDTH), _s(HEIGHT)), Image.Resampling.BICUBIC)


def _rgb(colour: str) -> np.ndarray:
    return np.array(ImageColor.getrgb(colour), dtype=np.float32)


def _petal(
    cx: float, cy: float, angle: float, inner: float, outer: float, width: float
) -> list[tuple[float, float]]:
    """A leaf from radius `inner` to `outer` along `angle`, `width` across at its widest."""
    points = []
    for side in (1, -1):
        steps = range(13) if side == 1 else range(12, -1, -1)
        for i in steps:
            t = i / 12
            r = inner + (outer - inner) * t
            w = math.sin(math.pi * t) * width / 2 * side
            points.append(
                (
                    cx + r * math.cos(angle) - w * math.sin(angle),
                    cy + r * math.sin(angle) + w * math.cos(angle),
                )
            )
    return points


def _rangoli(draw: ImageDraw.ImageDraw, cx: float, cy: float, radius: float, fill: tuple[int, ...]) -> None:
    """Concentric rings of petals and dots, like a rangoli."""
    cx, cy, radius = _s(cx), _s(cy), _s(radius)
    line = _s(2)
    for ring, (petals, inner, outer, width) in enumerate(
        [(8, 0.10, 0.36, 0.16), (16, 0.40, 0.66, 0.13), (24, 0.70, 0.94, 0.09)]
    ):
        offset = math.pi / petals * (ring % 2)
        for k in range(petals):
            angle = 2 * math.pi * k / petals + offset
            leaf = _petal(cx, cy, angle, inner * radius, outer * radius, width * radius)
            draw.polygon(leaf, outline=fill, width=line)
    for ring_r in (0.38, 0.68, 0.97):
        r = ring_r * radius
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=fill, width=line)
    for dots, ring_r in ((32, 1.04), (48, 1.12)):
        dot = _s(2.4)
        for k in range(dots):
            angle = 2 * math.pi * k / dots
            x, y = cx + ring_r * radius * math.cos(angle), cy + ring_r * radius * math.sin(angle)
            draw.ellipse((x - dot, y - dot, x + dot, y + dot), fill=fill)
    core = 0.06 * radius
    draw.ellipse((cx - core, cy - core, cx + core, cy + core), fill=fill)


def _halftone(draw: ImageDraw.ImageDraw, fill: tuple[int, ...]) -> None:
    """Dots that shrink away from the body's top-right corner."""
    corner = (PERFORATION_X, INSET)
    for x in range(PERFORATION_X - 8, PERFORATION_X - 200, -16):
        for y in range(INSET + 8, INSET + 200, 16):
            r = 4.2 * (1 - math.dist((x, y), corner) / 200)
            if r > 0.4:
                draw.ellipse((_s(x - r), _s(y - r), _s(x + r), _s(y + r)), fill=fill)


def _sparkle(draw: ImageDraw.ImageDraw, x: float, y: float, r: float, fill: str) -> None:
    """A four-pointed star."""
    points = []
    for k in range(8):
        reach = r if k % 2 == 0 else r * 0.28
        angle = math.pi / 4 * k - math.pi / 2
        points.append((_s(x + reach * math.cos(angle)), _s(y + reach * math.sin(angle))))
    draw.polygon(points, fill=fill)


def _tracked(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font, fill, tracking: float) -> int:
    """`text` with extra letter spacing; returns the right edge."""
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        x += draw.textlength(char, font=font) + _s(tracking)
    return x - _s(tracking)


def _tracked_width(draw: ImageDraw.ImageDraw, text: str, font, tracking: float) -> float:
    return draw.textlength(text, font=font) + _s(tracking) * (len(text) - 1)


def _ticket_mask() -> Image.Image:
    """The ticket outline: a rounded rectangle with a notch at each end of the perforation."""
    mask = Image.new("L", (_s(WIDTH), _s(HEIGHT)), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle(
        (_s(INSET), _s(INSET), _s(WIDTH - INSET), _s(HEIGHT - INSET)), _s(RADIUS), fill=255
    )
    for y in (INSET, HEIGHT - INSET):
        draw.ellipse(
            (_s(PERFORATION_X - NOTCH), _s(y - NOTCH), _s(PERFORATION_X + NOTCH), _s(y + NOTCH)), fill=0
        )
    return mask


def _draw_body(image: Image.Image, money_lines: list[str]) -> None:
    """The headline money line, wrapped big, and any further money lines as pills beneath it."""
    draw = ImageDraw.Draw(image)
    ribbon_font = _font(13, "Bold")
    ribbon = "PICKED FOR YOU" if money_lines else "SOMETHING FOR YOU"
    ribbon_w = _tracked_width(draw, ribbon, ribbon_font, 2.2) + _s(36)
    draw.rounded_rectangle((_s(BODY_LEFT), _s(52), _s(BODY_LEFT) + ribbon_w, _s(82)), _s(15), fill=GOLD)
    _sparkle(draw, BODY_LEFT + 15, 67, 6, INK)
    _tracked(draw, (_s(BODY_LEFT + 27), _s(58)), ribbon, ribbon_font, INK, 2.2)

    headline, *rest = money_lines or ["Have a look"]
    font, lines = _fitted_lines(draw, headline, 80, BODY_RIGHT - BODY_LEFT, 3)
    line_height = font.size * 1.08
    y = _s(104)
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    for line in lines:
        shadow_draw.text((_s(BODY_LEFT + 3), y + _s(4)), line, font=font, fill=(20, 10, 40, 90))
        y += line_height
    image.alpha_composite(shadow)
    y = _s(104)
    for line in lines:
        draw.text((_s(BODY_LEFT), y), line, font=font, fill=WHITE)
        y += line_height

    pill_font = _font(24, "SemiBold")
    y += _s(14)
    for line in rest:
        w = draw.textlength(line, font=pill_font)
        pill = Image.new("RGBA", image.size, (0, 0, 0, 0))
        ImageDraw.Draw(pill).rounded_rectangle(
            (_s(BODY_LEFT), y, _s(BODY_LEFT + 36) + w, y + _s(44)), _s(22), fill=(255, 255, 255, 56)
        )
        image.alpha_composite(pill)
        draw.text((_s(BODY_LEFT + 18), y + _s(6)), line, font=pill_font, fill=WHITE)
        y += _s(54)


def _draw_stub(draw: ImageDraw.ImageDraw, code_line: str, valid_line: str, code: str) -> None:
    """The code in a dashed box, the expiry under it, and a decorative barcode."""
    width = STUB_RIGHT - STUB_LEFT
    centre = _s((STUB_LEFT + STUB_RIGHT) / 2)
    label_font = _font(12, "Bold")

    def label(text: str, y: float) -> None:
        w = _tracked_width(draw, text, label_font, 2.4)
        _tracked(draw, (round(centre - w / 2), _s(y)), text, label_font, MUTED, 2.4)

    code_label, code_value = code_line.split(" ", 1)
    label(code_label.upper(), 56)
    box = (_s(STUB_LEFT), _s(78), _s(STUB_RIGHT), _s(130))
    draw.rounded_rectangle(box, _s(10), fill="#ffe6bd")
    _dashed_box(draw, box, _s(10))
    code_font = _fitted(draw, code_value, 26, "Bold", width - 20)
    draw.text((centre, _s(104)), code_value, font=code_font, fill=INK, anchor="mm")

    valid, until, valid_value = valid_line.split(" ", 2)
    label(f"{valid} {until}".upper(), 156)
    valid_font = _fitted(draw, valid_value, 24, "Bold", width)
    draw.text((centre, _s(192)), valid_value, font=valid_font, fill=INK, anchor="mm")

    rng = random.Random(code)
    x, top, bottom = float(STUB_LEFT), 300.0, 380.0
    while x < STUB_RIGHT - 3:
        bar = rng.choice((1.5, 1.5, 3, 4.5))
        draw.rectangle((_s(x), _s(top), _s(x + bar) - 1, _s(bottom)), fill=INK)
        x += bar + rng.choice((1.5, 3, 3, 4.5))
    _sparkle(draw, STUB_LEFT + 6, 248, 7, "#e0157a")
    _sparkle(draw, STUB_RIGHT - 10, 262, 10, GOLD)
    _sparkle(draw, STUB_LEFT + 40, 270, 4, "#7b3ff2")


def _dashed_box(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int) -> None:
    left, top, right, bottom = box
    dash, gap, line = _s(7), _s(5), _s(2)
    for y in (top, bottom - line):
        for x in range(left + radius, right - radius, dash + gap):
            draw.rectangle((x, y, min(x + dash, right - radius), y + line), fill=INK)
    for x in (left, right - line):
        for y in range(top + radius, bottom - radius, dash + gap):
            draw.rectangle((x, y, x + line, min(y + dash, bottom - radius)), fill=INK)
    for corner, start in (
        ((left, top), 180),
        ((right - 2 * radius, top), 270),
        ((right - 2 * radius, bottom - 2 * radius), 0),
        ((left, bottom - 2 * radius), 90),
    ):
        x, y = corner
        draw.arc((x, y, x + 2 * radius, y + 2 * radius), start, start + 90, fill=INK, width=line)


def render_offer_card(offer: Offer, catalog_names: dict[str, str]) -> bytes:
    """A PNG drawing exactly `offer_terms`: money lines big on the body, code and expiry on the stub."""
    *money_lines, code_line, valid_line = offer_terms(offer, catalog_names)
    start, end, glow = THEMES[offer.offer_type]
    size = (_s(WIDTH), _s(HEIGHT))

    image = Image.new("RGBA", size, OUTER)
    draw = ImageDraw.Draw(image)
    for x in range(10, WIDTH, 20):
        for y in range(10, HEIGHT, 20):
            draw.ellipse((_s(x - 1.6), _s(y - 1.6), _s(x + 1.6), _s(y + 1.6)), fill=OUTER_DOT)

    ticket = _gradient(start, end, glow).copy()
    pattern = Image.new("RGBA", size, (0, 0, 0, 0))
    pattern_draw = ImageDraw.Draw(pattern)
    _rangoli(pattern_draw, 470, 390, 200, (255, 255, 255, 72))
    _halftone(pattern_draw, (255, 255, 255, 60))
    ticket.alpha_composite(pattern)
    ticket_draw = ImageDraw.Draw(ticket)
    _sparkle(ticket_draw, 520, 66, 13, GOLD)
    _sparkle(ticket_draw, 494, 98, 6, WHITE)
    _sparkle(ticket_draw, 96, 392, 7, GOLD)
    ticket_draw.rectangle((_s(PERFORATION_X), 0, size[0], size[1]), fill=STUB)
    image.paste(ticket, (0, 0), _ticket_mask())

    _draw_body(image, money_lines)
    draw = ImageDraw.Draw(image)
    for y in range(INSET + NOTCH + 8, HEIGHT - INSET - NOTCH - 4, 14):
        draw.rounded_rectangle(
            (_s(PERFORATION_X - 1.5), _s(y), _s(PERFORATION_X + 1.5), _s(y + 7)), _s(1.5), fill=OUTER
        )
    _draw_stub(draw, code_line, valid_line, offer.code)

    out = BytesIO()
    image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS).convert("RGB").save(out, format="PNG")
    return out.getvalue()
