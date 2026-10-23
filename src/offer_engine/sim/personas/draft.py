"""Draft a Persona Card with Claude from a Customer's observable data (PLAN §4.2, QnA Q25).

The prompt is built only from a `ProfileSummary`: the profile, the last 180 days of events and Offers, and points,
as `customers.load_customer_state` loads them. It has no Ground Truth fields and no showcase case, so the card
can't reveal how the Customer responds to Offers beyond what their history shows (ADR 0002).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from offer_engine.customers import EVENT_DAYS
from offer_engine.domain import Catalog, CustomerState, OfferStatus

TOOL_NAME = "write_persona_card"
TIMEOUT_SECONDS = 60.0
MAX_TOKENS = 4000
EFFORT = "low"
MAX_PRODUCTS = 5
CARD_WORDS = (60, 100)
ATTEMPTS = 2
RECENT_DAYS = 30

SYSTEM_PROMPT = """\
You write Persona Cards for a demo of an offer engine run by a fictional Indian online marketplace. Every \
Customer is synthetic. A Persona Card is read by an actor who plays the Customer in Telegram chats, and by human \
testers who pick a Customer to play.

## The card
- 60 to 100 words of plain English, third person, present tense, starting with the Customer's name.
- Cover their situation, their needs and their shopping habits.
- Every habit or need must follow from the data given. You may invent a fictional Indian name, an age, a job \
and a home town that fit the city tier, device and categories, and nothing that contradicts the data.
- Mention past offers only as the data shows them (how many they got, claimed, used or ignored).
- Never predict the future: don't say whether they will buy, would buy anyway, need a discount, or how an offer \
would change what they do.
- No numbers for money or dates; words like "a few", "most weeks" and "lately" are fine.

## Variety
The showcase has several Customers. Vary them: men and women, ages from the early twenties to the sixties, many \
kinds of work and home towns across India. When you're shown how other cards start, make this person clearly \
different from each of them in gender or age, and in job, home town and name.

## The name
A first name and surname, common in India.

Answer by calling the write_persona_card tool exactly once.
"""

TOOL = {
    "name": TOOL_NAME,
    "description": "Save the Persona Card: the Customer's fictional name and the 60–100-word card.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "A fictional Indian first name and surname."},
            "card": {"type": "string", "description": "60–100 words, third person, starting with the name."},
        },
        "required": ["name", "card"],
        "additionalProperties": False,
    },
}


class DraftError(RuntimeError):
    """The agent's answer can't be turned into a card."""


@dataclass(frozen=True)
class ProfileSummary:
    """What the card writer may know about a Customer. Observable data only: never add Ground Truth here."""

    customer_id: str
    days_since_signup: int
    city_tier: int
    device: str
    channel: str
    loyalty_tier: str
    points_balance: int
    points_expire_in_days: int | None
    orders: int  # in the last 180 days
    spend: float
    days_since_last_order: int | None  # None: no order in the last 180 days
    returns: int
    sessions_last_30_days: int
    carts_abandoned: int
    carts_abandoned_last_30_days: int
    top_categories: tuple[str, ...]  # by product views and orders, most first
    recent_products: tuple[str, ...]  # names, newest first
    offers_received: int
    offers_claimed: int
    offers_redeemed: int
    offers_dismissed: int
    opted_out: bool


@dataclass(frozen=True)
class Draft:
    name: str
    card: str


def build_summary(state: CustomerState, catalog: Catalog, now: datetime) -> ProfileSummary:
    c = state.customer
    since = now - timedelta(days=EVENT_DAYS)
    recent = now - timedelta(days=RECENT_DAYS)
    events = [e for e in state.events if since <= e.at <= now]
    orders = [e for e in events if e.kind == "order"]
    abandoned = [e for e in events if e.kind == "cart_abandoned"]
    interest = Counter(e.category for e in events if e.kind in ("product_view", "order") and e.category)
    products: list[str] = []
    for e in sorted(events, key=lambda e: e.at, reverse=True):
        product = catalog.products.get(e.product_id) if e.product_id else None
        if product and e.kind in ("add_to_cart", "order", "product_view") and product.name not in products:
            products.append(product.name)
    statuses = Counter(o.status for o in state.offers)
    return ProfileSummary(
        customer_id=c.id,
        days_since_signup=(now - c.signup_at).days,
        city_tier=c.city_tier,
        device=c.device,
        channel=c.channel,
        loyalty_tier=c.loyalty_tier,
        points_balance=c.points_balance,
        points_expire_in_days=(c.points_expire_at - now).days
        if c.points_expire_at and c.points_balance
        else None,
        orders=len(orders),
        spend=sum(e.amount or 0 for e in orders),
        days_since_last_order=(now - max(e.at for e in orders)).days if orders else None,
        returns=sum(e.kind == "return" for e in events),
        sessions_last_30_days=sum(e.kind == "session" and e.at >= recent for e in events),
        carts_abandoned=len(abandoned),
        carts_abandoned_last_30_days=sum(e.at >= recent for e in abandoned),
        top_categories=tuple(cat for cat, _ in interest.most_common(3)),
        recent_products=tuple(products[:MAX_PRODUCTS]),
        offers_received=len(state.offers),
        offers_claimed=statuses[OfferStatus.CLAIMED] + statuses[OfferStatus.REDEEMED],
        offers_redeemed=statuses[OfferStatus.REDEEMED],
        offers_dismissed=statuses[OfferStatus.DISMISSED],
        opted_out=c.opted_out,
    )


def user_prompt(summary: ProfileSummary, others: tuple[str, ...] = ()) -> str:
    """`others`: the first sentence of each card already written for other showcase Customers."""
    s = summary
    last = (
        f"last order {_n(s.days_since_last_order, 'day')} ago"
        if s.days_since_last_order is not None
        else f"no order in the last {EVENT_DAYS} days"
    )
    expiry = (
        f", expiring in {_n(s.points_expire_in_days, 'day')}" if s.points_expire_in_days is not None else ""
    )
    lines = [
        f"## Customer {s.customer_id}",
        (
            f"- Signed up {_n(s.days_since_signup, 'day')} ago via {s.channel}; shops on {s.device}; "
            f"city tier {s.city_tier} (1 = metro, 3 = small town)."
        ),
        f"- Loyalty tier {s.loyalty_tier}; {s.points_balance} loyalty points{expiry}.",
        (
            f"- Last {EVENT_DAYS} days: {_n(s.orders, 'order')}, ₹{s.spend:,.0f} in total, {last}; "
            f"{_n(s.returns, 'return')}."
        ),
        f"- {_n(s.sessions_last_30_days, 'visit')} in the last {RECENT_DAYS} days.",
        (
            f"- Carts left without buying: {s.carts_abandoned} in {EVENT_DAYS} days, "
            f"{s.carts_abandoned_last_30_days} in the last {RECENT_DAYS}."
        ),
        "- Most browsed and bought categories: " + (", ".join(s.top_categories) or "none yet") + ".",
        "- Recent products (newest first): " + ("; ".join(s.recent_products) or "none") + ".",
        (
            f"- Past offers: {s.offers_received} received, {s.offers_claimed} claimed, "
            f"{s.offers_redeemed} used on an order, {s.offers_dismissed} dismissed."
        ),
    ]
    if s.opted_out:
        lines.append("- Has turned off offer messages.")
    if others:
        lines.append("\n## Other cards start like this")
        lines += [f"- {first}" for first in others]
    return "\n".join(lines)


def _n(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def draft_card(client: Any, model: str, summary: ProfileSummary, others: tuple[str, ...] = ()) -> Draft:
    """Up to ATTEMPTS Messages API calls: a card outside CARD_WORDS is asked for again once, and the last answer is
    returned whatever its length. Raises DraftError for a refusal, a cut-off answer or a missing tool call.
    """
    prompt = user_prompt(summary, others)
    for _ in range(ATTEMPTS):
        result = _ask(client, model, prompt)
        words = len(result.card.split())
        if CARD_WORDS[0] <= words <= CARD_WORDS[1]:
            break
        prompt = user_prompt(summary, others) + (
            f"\n\nA first attempt came out at {words} words. Keep the card between {CARD_WORDS[0]} and "
            f"{CARD_WORDS[1]} words."
        )
    return result


def _ask(client: Any, model: str, prompt: str) -> Draft:
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[TOOL],
        tool_choice={"type": "auto", "disable_parallel_tool_use": True},
        output_config={"effort": EFFORT},
        messages=[{"role": "user", "content": prompt}],
        timeout=TIMEOUT_SECONDS,
    )
    if response.stop_reason == "refusal":
        raise DraftError("the agent refused")
    if response.stop_reason == "max_tokens":
        raise DraftError("the agent's answer was cut off at max_tokens")
    for block in response.content:
        if block.type == "tool_use" and block.name == TOOL_NAME:
            name, card = str(block.input["name"]).strip(), " ".join(str(block.input["card"]).split())
            if not name or not card:
                raise DraftError("the agent left the name or card empty")
            return Draft(name, card)
    raise DraftError(f"the agent didn't call {TOOL_NAME}")
