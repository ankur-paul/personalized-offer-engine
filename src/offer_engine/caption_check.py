"""Caption Check (PLAN §3.5 step 3, ADR 0005): reject an agent-written caption that contradicts or adds to the
Offer's terms, invents urgency, or is too long.

The Offer Card draws the terms, so the caption may only repeat them: every number it states must be one of the
Offer's own terms. Phrases live in tables; to catch a new phrasing, add a row. Each reason is `code: detail`, at most
one per code, in `REASON_CODES` order.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Callable

from offer_engine.domain import Catalog, OfferType, Proposal, RuleSet

MAX_LENGTH = 280
DEFAULT_VALIDITY_DAYS = RuleSet().offer_validity_days
REASON_CODES = (
    "number_mismatch",
    "deadline_mismatch",
    "invented_urgency",
    "unoffered_promise",
    "too_long",
    "empty",
)

# --- Phrase tables -----------------------------------------------------------------------------
# Patterns run on the caption after NFKC, lower-casing and straight apostrophes.

WEEKDAY = r"(?:mon|tues|wednes|thurs|fri|satur|sun)day"
MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)

# Spoken numbers. "one" alone is skipped ("the one you loved"); Hindi words that are also English words are left out.
UNITS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen"
    " seventeen eighteen nineteen"
)
TENS = "twenty thirty forty fifty sixty seventy eighty ninety"
NUMBER_WORDS = {
    **{word: i for i, word in enumerate(UNITS.split())},
    **{word: 10 * i for i, word in enumerate(TENS.split(), start=2)},
    "pachas": 50,
    "pachaas": 50,
    "sau": 100,
}
SCALE_WORDS = {
    "hundred": 100,
    "thousand": 1_000,
    "hazaar": 1_000,
    "hazar": 1_000,
    "lakh": 100_000,
    "lac": 100_000,
}
_ANY_NUMBER_WORD = "|".join(sorted([*NUMBER_WORDS, *SCALE_WORDS], key=len, reverse=True))

# Masked before numbers are read, so "9pm" is a deadline, not also a stray 9.
DEADLINES = (
    rf"\b{WEEKDAY}s?\b",
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{MONTH}\b",
    rf"\b{MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?\b",
    r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b",
    r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)(?![a-z])",
    r"\b\d{1,2}:\d{2}\b",
    r"\b\d{1,2}\s*baje\b",
    rf"\b(?:\d+|{_ANY_NUMBER_WORD})\s*(?:hours?|hrs?|h|minutes?|mins?|ghante|ghanton)\b",
    r"\b(?:tonight|tomorrow|midnight|noon|end of (?:the )?day|eod)\b",
    r"\b(?:only|just|ends?|valid|till|until)\s+today\b|\btoday\s+only\b",
    r"\bthis weekend\b|\bweekend only\b",
    r"\b(?:sirf aaj|aaj hi|aaj raat|aaj tak|kal tak)\b",
)

URGENCY = (
    r"\bhurry\b",
    r"\blast (?:chance|few)\b",
    r"\b(?:only\s+)?(?:a\s+)?few\s+(?:left|remaining)\b",
    r"\bonly\s+\d+\s+(?:left|remaining)\b",
    r"\bselling\s+(?:out|fast)\b",
    r"\b(?:almost|nearly)\s+(?:gone|sold out)\b",
    r"\bbefore (?:it's|its|they're|theyre) gone\b",
    r"\bdon'?t miss(?: out)?\b",
    r"\bact (?:now|fast)\b",
    r"\blimited (?:time|stock|period)\b",
    r"\b(?:ends|ending) soon\b",
    r"\bwhile (?:stocks?|supplies) lasts?\b",
    r"\b(?:running out|now or never|final hours)\b",
    r"\b(?:jaldi|khatam|mauka)\b",
    r"[⏳⌛⏰🚨]",
)


def _always(proposal: Proposal) -> bool:
    return True


def _unless_type(offer_type: OfferType) -> Callable[[Proposal], bool]:
    return lambda proposal: proposal.offer_type != offer_type


def _only_type(offer_type: OfferType) -> Callable[[Proposal], bool]:
    return lambda proposal: proposal.offer_type == offer_type


def _has_param(name: str) -> Callable[[Proposal], bool]:
    return lambda proposal: name in proposal.params


# (pattern, applies to this Proposal?)
PROMISES: tuple[tuple[str, Callable[[Proposal], bool]], ...] = (
    (r"\bfree\s+gifts?\b|\bfreebies?\b", _always),
    (r"\bcash\s*back\b", _always),
    (r"\bguarantee[ds]?\b|\b(?:lowest|best) price\b", _always),
    (r"\bfree\s+returns?\b", _always),
    (r"\bbuy\s+(?:one|1)\s+get\s+(?:one|1)\b|\bbogo\b|\b1\s*\+\s*1\b", _always),
    (
        r"\b(?:extra|additional)\s+(?:\S+\s+)?(?:discount|savings?|off)\b|\b(?:extra|additional)\s+\d[\d.,]*\s*%",
        _always,
    ),
    (
        (
            r"\bfree\s+(?:delivery|shipping)\b|\bzero\s+(?:delivery|shipping)\b"
            r"|\bno\s+(?:delivery|shipping)\s+(?:fee|charges?)\b|\bshipping'?s on us\b"
        ),
        _unless_type(OfferType.FREE_SHIPPING),
    ),
    (r"\bno\s+min(?:imum)?\b", _has_param("min_basket")),
    (r"\b(?:bonus|extra)\s+points\b", _unless_type(OfferType.POINTS_MULTIPLIER)),
    (r"\b(?:discount|coupon|voucher|promo\s*code)s?\b", _only_type(OfferType.NUDGE)),
)

# --- Numbers -----------------------------------------------------------------------------------

PCT, MONEY, MULTIPLIER, PLAIN = "pct", "money", "multiplier", "plain"
TERM_KINDS = {"pct": PCT, "cap": MONEY, "amount": MONEY, "min_basket": MONEY, "multiplier": MULTIPLIER}

NUMERAL = re.compile(
    r"(?P<pre>₹|(?<![a-z])(?:rs|inr)\.?|(?<![a-z])x)?\s*"
    r"(?P<num>\d+(?:,\d+)*(?:\.\d+)?)"
    r"(?:\s*(?P<scale>k|lakh|lac)(?![a-z]))?"
    r"(?:\s*(?P<suf>%|percent\b|per\s*cent\b|pct\b|pc\b|x(?![a-z])|times\b|rupees\b|rs\b|/-))?"
)
NUMBER_RUN = re.compile(rf"\b(?:{_ANY_NUMBER_WORD})(?:[\s-]+(?:and[\s-]+)?(?:{_ANY_NUMBER_WORD}))*\b")
SCALES = {"k": 1_000, "lakh": 100_000, "lac": 100_000}
# Words that fix both the kind and the value.
FIXED_NUMBERS = (
    (r"\b(?:double|twice|dugn[ae])\b", MULTIPLIER, 2.0),
    (r"\b(?:triple|thrice)\b", MULTIPLIER, 3.0),
    (r"\bhalf\s+(?:price|off)\b", PCT, 50.0),
)
WORD_SUFFIX_KINDS = (
    (re.compile(r"\s*(?:%|percent\b|per\s*cent\b)"), PCT),
    (re.compile(r"\s*(?:rupees|rs)\b"), MONEY),
    (re.compile(r"\s*(?:x|times)\b"), MULTIPLIER),
)
MONEY_BEFORE = re.compile(r"(?:₹|\b(?:rs|inr)\.?)\s*$")


def check(
    caption: str, proposal: Proposal, catalog: Catalog, *, validity_days: int = DEFAULT_VALIDITY_DAYS
) -> list[str]:
    """Reasons the caption fails, empty if it passes. `validity_days` is the Rule `offer_validity_days`."""
    if not caption.strip():
        return ["empty: blank caption"]
    text = _normalise(caption)
    text = _mask_featured_names(text, proposal, catalog)
    found: dict[str, list[str]] = {code: [] for code in REASON_CODES}

    deadlines = _matches(DEADLINES, text)
    found["deadline_mismatch"] = [m.group().strip() for m in deadlines]
    masked = _mask(text, deadlines)
    found["number_mismatch"] = _number_mismatches(masked, proposal, validity_days)
    found["invented_urgency"] = [m.group() for m in _matches(URGENCY, text)]
    found["unoffered_promise"] = [
        m.group() for pattern, applies in PROMISES if applies(proposal) for m in re.finditer(pattern, text)
    ]
    length = len(caption.strip())
    if length > MAX_LENGTH:
        found["too_long"] = [f"{length} > {MAX_LENGTH} characters"]

    return [f"{code}: {', '.join(dict.fromkeys(found[code]))}" for code in REASON_CODES if found[code]]


def _normalise(caption: str) -> str:
    """NFKC folds full-width digits; dropping the emoji variation selector and keycap mark turns 2️⃣ into 2."""
    text = unicodedata.normalize("NFKC", caption)
    for mark in ("️", "⃣"):
        text = text.replace(mark, "")
    return text.replace("’", "'").replace("‘", "'").lower()


def _mask_featured_names(text: str, proposal: Proposal, catalog: Catalog) -> str:
    """Digits inside a featured product's name ("Basmati Rice 5kg") are part of the name, not a claim."""
    for product_id in proposal.featured_product_ids:
        product = catalog.products.get(product_id)
        if product is None:
            continue
        for token in product.name.lower().split():
            if any(ch.isdigit() for ch in token):
                text = re.sub(rf"(?<!\w){re.escape(token)}(?!\w)", " ", text)
    return text


def _matches(patterns: tuple[str, ...], text: str) -> list[re.Match[str]]:
    return sorted((m for p in patterns for m in re.finditer(p, text)), key=lambda m: m.start())


def _mask(text: str, matches: list[re.Match[str]]) -> str:
    chars = list(text)
    for m in matches:
        chars[m.start() : m.end()] = " " * (m.end() - m.start())
    return "".join(chars)


def _number_mismatches(text: str, proposal: Proposal, validity_days: int) -> list[str]:
    allowed: dict[str, list[float]] = {PCT: [], MONEY: [], MULTIPLIER: [], PLAIN: [float(validity_days)]}
    for name, value in proposal.params.items():
        allowed[TERM_KINDS.get(name, PLAIN)].append(value)
        allowed[PLAIN].append(value)

    return [
        shown
        for shown, kind, value in _numbers(text)
        if not any(math.isclose(value, term, abs_tol=0.005) for term in allowed[kind])
    ]


def _numbers(text: str) -> list[tuple[str, str, float]]:
    """(as written, kind, value) for every number in the text, in order."""
    found: list[tuple[int, str, str, float]] = []
    for m in NUMERAL.finditer(text):
        value = float(m["num"].replace(",", "")) * SCALES.get(m["scale"] or "", 1)
        found.append((m.start(), m.group().strip(), _numeral_kind(m["pre"], m["suf"]), value))
    for m in NUMBER_RUN.finditer(text):
        if m.group() == "one":
            continue
        kind = next((k for suffix, k in WORD_SUFFIX_KINDS if suffix.match(text, m.end())), PLAIN)
        if kind == PLAIN and MONEY_BEFORE.search(text, 0, m.start()):
            kind = MONEY
        found.append((m.start(), m.group(), kind, _word_value(m.group())))
    for pattern, kind, value in FIXED_NUMBERS:
        found += [(m.start(), m.group(), kind, value) for m in re.finditer(pattern, text)]
    return [(shown, kind, value) for _, shown, kind, value in sorted(found)]


def _numeral_kind(pre: str | None, suf: str | None) -> str:
    pre = (pre or "").rstrip(".")
    suf = re.sub(r"\s+", "", suf or "")
    if suf in ("%", "percent", "pct", "pc"):  # "per cent" arrives as "percent"
        return PCT
    if pre in ("₹", "rs", "inr") or suf in ("rupees", "rs", "/-"):
        return MONEY
    if pre == "x" or suf in ("x", "times"):
        return MULTIPLIER
    return PLAIN


def _word_value(run: str) -> float:
    """'twenty-five' → 25, 'a hundred' → 100, 'one hundred and fifty' → 150."""
    total = current = 0
    for word in re.split(r"[\s-]+", run):
        if word in NUMBER_WORDS:
            current += NUMBER_WORDS[word]
        elif word in SCALE_WORDS:
            current = (current or 1) * SCALE_WORDS[word]
            if SCALE_WORDS[word] >= 1_000:
                total, current = total + current, 0
    return float(total + current)
