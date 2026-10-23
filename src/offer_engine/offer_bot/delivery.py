"""Offer delivery: every few wall-clock seconds the Offer Bot sends due Offer Cards and `outbox` messages.

An Offer is due when it is queued, its Customer is chat-attached and not opted out, and `send_at` has passed on the
Simulation Clock but `expires_at` hasn't. A failed send stays queued and is retried on the next run.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import Application, ContextTypes

from offer_engine import clock
from offer_engine.db import connect
from offer_engine.domain import Offer, OfferSource, OfferStatus, OfferType
from offer_engine.offer_card import render_offer_card

log = logging.getLogger(__name__)

INTERVAL_SECONDS = 5
# Callback data is "<action>:<code>"; Stop carries no code.
CLAIM, NOT_NOW, STOP = "claim", "notnow", "stop"


@dataclass(frozen=True)
class Delivery:
    offer: Offer
    chat_id: int


@dataclass(frozen=True)
class OutboxMessage:
    id: int
    chat_id: int
    text: str


def due_offers(conn: sqlite3.Connection, now: datetime) -> list[Delivery]:
    """Queued Offers to chat-attached, opted-in Customers whose `send_at` has passed by `now`, oldest first."""
    rows = conn.execute(
        "SELECT o.*, ch.chat_id FROM offers o JOIN chats ch ON ch.customer_id = o.customer_id"
        " JOIN customers c ON c.id = o.customer_id"
        " WHERE o.status = ? AND o.send_at <= ? AND o.expires_at > ? AND c.opted_out = 0"
        " ORDER BY o.send_at, o.id",
        (OfferStatus.QUEUED, _iso(now), _iso(now)),
    )
    return [Delivery(_offer(row), row["chat_id"]) for row in rows]


def unsent_messages(conn: sqlite3.Connection) -> list[OutboxMessage]:
    rows = conn.execute("SELECT id, chat_id, text FROM outbox WHERE sent_at IS NULL ORDER BY id")
    return [OutboxMessage(*row) for row in rows]


def queue_message(conn: sqlite3.Connection, chat_id: int, text: str) -> None:
    """Add a message for the Offer Bot to send on its next run. The caller commits."""
    conn.execute(
        "INSERT INTO outbox (chat_id, text, created_at) VALUES (?, ?, ?)",
        (chat_id, text, _iso(clock.now(conn))),
    )


def mark_offer_sent(conn: sqlite3.Connection, offer_id: int) -> None:
    conn.execute(
        "UPDATE offers SET status = ?, sent_at = ? WHERE id = ? AND status = ?",
        (OfferStatus.SENT, _iso(clock.now(conn)), offer_id, OfferStatus.QUEUED),
    )
    conn.commit()


def mark_message_sent(conn: sqlite3.Connection, message_id: int) -> None:
    conn.execute("UPDATE outbox SET sent_at = ? WHERE id = ?", (_iso(clock.now(conn)), message_id))
    conn.commit()


def card_caption(offer: Offer) -> str:
    return f"{offer.caption}\n\nCode: {offer.code}" if offer.caption else f"Code: {offer.code}"


def card_buttons(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Claim", callback_data=f"{CLAIM}:{code}"),
                InlineKeyboardButton("Not now", callback_data=f"{NOT_NOW}:{code}"),
                InlineKeyboardButton("Stop", callback_data=STOP),
            ]
        ]
    )


async def deliver(context: ContextTypes.DEFAULT_TYPE) -> None:
    """One delivery run: due Offer Cards, then outbox messages."""
    conn = connect(context.bot_data["settings"].db_path)
    try:
        for delivery in due_offers(conn, clock.now(conn)):
            offer = delivery.offer
            try:
                await context.bot.send_photo(
                    delivery.chat_id,
                    photo=render_offer_card(offer, {}),
                    caption=card_caption(offer),
                    reply_markup=card_buttons(offer.code),
                )
            except TelegramError as exc:
                log.warning("Offer %s to chat %s not sent: %s", offer.code, delivery.chat_id, exc)
                continue
            mark_offer_sent(conn, offer.id)
            log.info("sent Offer %s to %s (chat %s)", offer.code, offer.customer_id, delivery.chat_id)
        for message in unsent_messages(conn):
            try:
                await context.bot.send_message(message.chat_id, message.text)
            except TelegramError as exc:
                log.warning("outbox message %s to chat %s not sent: %s", message.id, message.chat_id, exc)
                continue
            mark_message_sent(conn, message.id)
    finally:
        conn.close()


def register(app: Application) -> None:
    app.job_queue.run_repeating(deliver, interval=INTERVAL_SECONDS, first=1, name="delivery")


def _offer(row: sqlite3.Row) -> Offer:
    return Offer(
        id=row["id"],
        code=row["code"],
        customer_id=row["customer_id"],
        offer_type=OfferType(row["offer_type"]),
        category=row["category"],
        params=json.loads(row["params"]),
        featured_product_ids=tuple(json.loads(row["featured_product_ids"])),
        created_at=datetime.fromisoformat(row["created_at"]),
        send_at=datetime.fromisoformat(row["send_at"]),
        expires_at=datetime.fromisoformat(row["expires_at"]),
        caption=row["caption"],
        rule_version=row["rule_version"],
        worst_case_cost=row["worst_case_cost"],
        expected_cost=row["expected_cost"],
        status=OfferStatus(row["status"]),
        source=OfferSource(row["source"]),
    )


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="seconds")
