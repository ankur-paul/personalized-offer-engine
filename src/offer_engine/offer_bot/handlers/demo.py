"""The M1 demo: `/start` links a Tester to demo Customer C00001 and sends a hard-coded Offer Card; `/claim CODE`
is acknowledged. T10 and T25 replace it with real delivery and Tester flows."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta

from telegram import Bot, Message, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from offer_engine import clock
from offer_engine.db import connect
from offer_engine.domain import ChatKind, Offer, OfferSource, OfferStatus, OfferType, RuleSet
from offer_engine.offer_card import render_offer_card

log = logging.getLogger(__name__)

DEMO_CUSTOMER_ID = "C00001"
DEMO_CODE = "POE-DEMO01"
DEMO_CATALOG_NAMES = {"fashion": "Fashion"}
DEMO_CAPTION = f"Still thinking about those fashion picks? This one's for you.\nCode: {DEMO_CODE}"
# Text, not a command filter: whether a bot's private message gets a bot_command entity is undocumented.
CLAIM_PATTERN = r"(?i)^/claim(?:@\w+)?(?:\s+(\S+))?\s*$"


def demo_offer(now: datetime) -> Offer:
    """15% off fashion, ₹300 cap, valid for `offer_validity_days` from `now`."""
    return Offer(
        id=None,
        code=DEMO_CODE,
        customer_id=DEMO_CUSTOMER_ID,
        offer_type=OfferType.PCT_CATEGORY,
        category="fashion",
        params={"pct": 15.0, "cap": 300.0},
        featured_product_ids=(),
        created_at=now,
        send_at=now,
        expires_at=now + timedelta(days=RuleSet().offer_validity_days),
        caption=DEMO_CAPTION,
        rule_version=0,
        worst_case_cost=300.0,
        expected_cost=300.0,
        status=OfferStatus.SENT,
        source=OfferSource.LIVE,
    )


def link_tester(conn: sqlite3.Connection, chat_id: int, now: datetime) -> None:
    """Make `chat_id` the Tester chat of the demo Customer, creating a minimal Customer row if missing."""
    conn.execute(
        "INSERT OR IGNORE INTO customers (id, signup_at, city_tier, device, channel, loyalty_tier)"
        " VALUES (?, ?, 1, 'android', 'organic', 'silver')",
        (DEMO_CUSTOMER_ID, (now - timedelta(days=30)).isoformat(timespec="seconds")),
    )
    conn.execute(
        "INSERT INTO chats (customer_id, chat_id, kind) VALUES (?, ?, ?)"
        " ON CONFLICT (customer_id) DO UPDATE SET chat_id = excluded.chat_id, kind = excluded.kind",
        (DEMO_CUSTOMER_ID, chat_id, ChatKind.TESTER.value),
    )
    conn.commit()


def claim_reply(code: str | None) -> str:
    if not code:
        return f"Send /claim followed by the code, e.g. /claim {DEMO_CODE}"
    if code.upper() != DEMO_CODE:
        return f"No Offer has the code {code}."
    return f"Claimed {DEMO_CODE}. Show this code at checkout."


async def send_demo_card(bot: Bot, chat_id: int | str, now: datetime) -> Message:
    offer = demo_offer(now)
    return await bot.send_photo(
        chat_id, photo=render_offer_card(offer, DEMO_CATALOG_NAMES), caption=offer.caption
    )


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or user.is_bot:
        return
    conn = connect(context.bot_data["settings"].db_path)
    try:
        now = clock.now(conn)
        link_tester(conn, update.effective_chat.id, now)
    finally:
        conn.close()
    log.info("Tester chat %s linked to %s", update.effective_chat.id, DEMO_CUSTOMER_ID)
    await send_demo_card(context.bot, update.effective_chat.id, now)


async def on_claim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    code = context.matches[0].group(1)
    user = update.effective_user
    sender = f"@{user.username}" if user and user.username else str(update.effective_chat.id)
    kind = "bot" if user and user.is_bot else "tester"
    if code and code.upper() == DEMO_CODE:
        log.info("Claim %s from %s %s", DEMO_CODE, kind, sender)
    await update.effective_message.reply_text(claim_reply(code))


def register(app: Application) -> None:
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(CLAIM_PATTERN), on_claim))
