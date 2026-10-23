"""The M1 demo `/start`: links a Tester to demo Customer C00001 and turns their Offers back on. From a Customer
Bot it only turns Offers back on. T25 replaces it with real Tester flows."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from offer_engine import clock
from offer_engine.db import connect
from offer_engine.domain import ChatKind
from offer_engine.offer_bot import responses

log = logging.getLogger(__name__)

DEMO_CUSTOMER_ID = "C00001"
LINKED = (
    f"You're demo Customer {DEMO_CUSTOMER_ID}. Offers for {DEMO_CUSTOMER_ID} arrive here as Offer Cards; "
    "tap Claim, Not now or Stop."
)
# Customer Bots send `/start` as text, which may not carry a bot_command entity.
START_PATTERN = r"(?i)^/start(?:@\w+)?\s*$"


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


def start(conn: sqlite3.Connection, chat_id: int, is_bot: bool) -> str:
    """Link a Tester's chat to the demo Customer, then opt the chat's Customers back in. The reply text."""
    if not is_bot:
        link_tester(conn, chat_id, clock.now(conn))
        log.info("Tester chat %s linked to %s", chat_id, DEMO_CUSTOMER_ID)
    reply = responses.restart(conn, chat_id)
    if is_bot or reply == responses.NOT_LINKED:
        return reply
    return LINKED if reply == responses.ALREADY_ON else f"{reply} {LINKED}"


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    conn = connect(context.bot_data["settings"].db_path)
    try:
        reply = start(conn, update.effective_chat.id, bool(user and user.is_bot))
    finally:
        conn.close()
    await update.effective_message.reply_text(reply)


def register(app: Application) -> None:
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(START_PATTERN), on_start))
