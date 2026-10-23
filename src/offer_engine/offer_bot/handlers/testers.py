"""Testers (PLAN §4.1, QnA Q10, Q16): a human `/start`s the Offer Bot, picks a Customer from Persona Card buttons or
Surprise me, and plays their own copy of it. `/offers` asks the engine for an Offer now, `/whoami` names the Customer
and `/switch` picks again. From a Customer Bot, `/start` only turns Offers back on."""

from __future__ import annotations

import asyncio
import logging
import random
import sqlite3
from datetime import datetime
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from offer_engine import clock, personas, pipeline
from offer_engine.db import connect
from offer_engine.domain import RuleSet, TriggerKind
from offer_engine.offer_bot import responses
from offer_engine.personas import CASE_LABELS, PersonaCard
from offer_engine.rules import in_holdout
from offer_engine.rules_store import current_rules
from offer_engine.testers import create_tester_copy, played_by

log = logging.getLogger(__name__)

WELCOME = "Welcome! Pick a Customer to play. You'll get the offers our engine decides for them."
PICK_AGAIN = "Pick a Customer to play."
NO_CARDS = "No Customers are ready to play yet. Ask the marketing team to freeze the Persona Cards."
NOT_PLAYING = "You're not playing a Customer yet. Send /start to pick one."
UNKNOWN_PICK = "That Customer isn't available any more. Send /start to pick again."
# A console step holds the database while it runs; the connection gives up after 10 s.
BUSY = "The marketplace is busy moving the simulated clock. Try again in a few seconds."
HOLDOUT = (
    "You're playing {name}, who is in the control group (Holdout). They never receive offers, so we can measure "
    "what offers change."
)
PLAYING = "Simulated date: {date}. Offers arrive as the marketing team advances the clock. Send /offers to ask for one now."

# Callback data is "pick:<Customer ID>" or "pick:surprise".
PICK, SURPRISE = "pick", "surprise"
PICK_PATTERN = rf"^{PICK}:(\S+)$"
# Customer Bots send `/start` as text, which may not carry a bot_command entity.
START_PATTERN = r"(?i)^/start(?:@\w+)?\s*$"


def playable(conn: sqlite3.Connection, directory: Path = personas.PERSONAS_DIR) -> list[PersonaCard]:
    """Frozen Persona Cards whose Customer exists in this world, in CASES order."""
    return [
        card
        for card in personas.load_all(directory, frozen_only=True)
        if conn.execute("SELECT 1 FROM customers WHERE id = ?", (card.customer_id,)).fetchone()
    ]


def picker(cards: list[PersonaCard]) -> InlineKeyboardMarkup:
    """One button per card, then Surprise me."""
    rows = [
        [
            InlineKeyboardButton(
                f"{c.name} · {CASE_LABELS.get(c.case, c.case)}", callback_data=f"{PICK}:{c.customer_id}"
            )
        ]
        for c in cards
    ]
    rows.append([InlineKeyboardButton("Surprise me", callback_data=f"{PICK}:{SURPRISE}")])
    return InlineKeyboardMarkup(rows)


def start(
    conn: sqlite3.Connection, chat_id: int, directory: Path = personas.PERSONAS_DIR
) -> tuple[str, list]:
    """Turn Offers back on for the chat's Customer, if any. The reply text and the cards to offer."""
    restarted = responses.restart(conn, chat_id) == responses.RESTARTED
    cards = playable(conn, directory)
    if not cards:
        return (f"{responses.RESTARTED} {NO_CARDS}" if restarted else NO_CARDS), []
    if restarted:
        return f"{responses.RESTARTED} Or pick a different Customer to play.", cards
    return WELCOME, cards


def pick(
    conn: sqlite3.Connection,
    choice: str,
    telegram_user_id: int,
    chat_id: int,
    directory: Path = personas.PERSONAS_DIR,
    rng: random.Random | None = None,
) -> str:
    """Create or reuse the Tester's copy of the picked Customer (or a random one) and introduce it."""
    cards = playable(conn, directory)
    if choice == SURPRISE and cards:
        card = (rng or random).choice(cards)
    else:
        card = next((c for c in cards if c.customer_id == choice), None)
    if card is None:
        return UNKNOWN_PICK
    cid = create_tester_copy(conn, card.customer_id, telegram_user_id, chat_id)
    log.info("Tester chat %s plays %s", chat_id, cid)
    _, rules = current_rules(conn)
    if in_holdout(cid, rules.holdout_pct):
        return f"{card.card}\n\n{HOLDOUT.format(name=card.name)}"
    return f"{card.card}\n\n{PLAYING.format(date=_date(clock.now(conn)))}"


def request_offer(conn: sqlite3.Connection, chat_id: int, directory: Path = personas.PERSONAS_DIR) -> str:
    """Run the pipeline for the chat's Customer now (Trigger `on_request`) and say what it decided."""
    cid = played_by(conn, chat_id)
    if cid is None:
        return NOT_PLAYING
    name = _card(conn, cid, directory).name
    now = clock.now(conn)
    decision = pipeline.decide(conn, cid, TriggerKind.ON_REQUEST, now)
    log.info("/offers for %s: offer %s, binding %s", cid, decision.offer_id, decision.binding_rule)
    if decision.offer_id is None:
        _, rules = current_rules(conn)
        return f"No offer right now: {no_offer_reason(name, decision.binding_rule, rules)}"
    send_at = datetime.fromisoformat(
        conn.execute("SELECT send_at FROM offers WHERE id = ?", (decision.offer_id,)).fetchone()[0]
    )
    if send_at <= now:
        return f"The engine picked an offer for {name}. It's on its way."
    return (
        f"The engine picked an offer for {name}. It goes out at {send_at.day} {send_at:%b, %H:%M} simulated time, "
        "once the marketing team advances the clock that far."
    )


def no_offer_reason(name: str, binding_rule: str | None, rules: RuleSet) -> str:
    """The Binding Rule of a No Offer Decision in plain words."""
    if binding_rule == "opt_out":
        return f"{name} turned offers off. Send /start to turn them back on."
    if binding_rule == "holdout_pct":
        return f"{name} is in the control group (Holdout), so they never receive offers."
    if binding_rule == "fatigue_dismissals":
        return (
            f"{name} tapped Not now {_count(rules.fatigue_dismissals, 'time')} within "
            f"{_count(rules.fatigue_window_days, 'day')}, so offers are paused for "
            f"{_count(rules.fatigue_pause_days, 'day')}."
        )
    if binding_rule == "frequency_cap_count":
        period = (
            "this week"
            if rules.frequency_cap_days == 7
            else f"in the last {_count(rules.frequency_cap_days, 'day')}"
        )
        return f"{name} already got {_count(rules.frequency_cap_count, 'offer')} {period}."
    if binding_rule == "cooldown_days_after_redemption":
        days = _count(rules.cooldown_days_after_redemption, "day")
        return f"{name} used an offer in the last {days}, so the next one waits."
    if binding_rule == "min_days_since_signup":
        return f"{name} signed up less than {_count(rules.min_days_since_signup, 'day')} ago."
    if binding_rule == pipeline.FALLBACK_FAILED:
        return "the engine couldn't find an offer that passes every Rule."
    return f"none of the offers the Rules allow is worth its cost for {name}."


def whoami(conn: sqlite3.Connection, chat_id: int, directory: Path = personas.PERSONAS_DIR) -> str:
    cid = played_by(conn, chat_id)
    if cid is None:
        return NOT_PLAYING
    card = _card(conn, cid, directory)
    case = f" ({CASE_LABELS.get(card.case, card.case)})" if card.case else ""
    return (
        f"You're playing {card.name}{case}, Customer {cid}. Simulated date: {_date(clock.now(conn))}. "
        "Send /switch to pick someone else."
    )


def _card(conn: sqlite3.Connection, cid: str, directory: Path) -> PersonaCard:
    """The Persona Card of a copy's source; a stand-in named after the source if the card is gone."""
    row = conn.execute("SELECT source_customer_id FROM customers WHERE id = ?", (cid,)).fetchone()
    source = row[0] if row and row[0] else cid
    path = personas.path_for(source, directory)
    if path.is_file():
        return personas.load(path)
    return PersonaCard(source, "", f"Customer {source}", "", False, "", 0, 0)


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _date(at: datetime) -> str:
    return f"{at.day} {at:%b %Y}"


# --- Telegram handlers -------------------------------------------------------------------------


def _directory(context: ContextTypes.DEFAULT_TYPE) -> Path:
    return context.bot_data.get("personas_dir", personas.PERSONAS_DIR)


def _db(context: ContextTypes.DEFAULT_TYPE):
    return context.bot_data["settings"].db_path


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id
    conn = connect(_db(context))
    try:
        if user and user.is_bot:
            await update.effective_message.reply_text(responses.restart(conn, chat_id))
            return
        reply, cards = start(conn, chat_id, _directory(context))
    finally:
        conn.close()
    await update.effective_message.reply_text(reply, reply_markup=picker(cards) if cards else None)


async def on_switch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = connect(_db(context))
    try:
        cards = playable(conn, _directory(context))
    finally:
        conn.close()
    if not cards:
        await update.effective_message.reply_text(NO_CARDS)
        return
    await update.effective_message.reply_text(PICK_AGAIN, reply_markup=picker(cards))


async def on_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    conn = connect(_db(context))
    try:
        reply = pick(
            conn, context.matches[0].group(1), query.from_user.id, query.message.chat.id, _directory(context)
        )
    except sqlite3.OperationalError as exc:
        log.warning("pick from chat %s failed: %s", query.message.chat.id, exc)
        reply = BUSY
    finally:
        conn.close()
    try:
        await query.answer()
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError as exc:
        log.info("pick buttons not answered or removed: %s", exc)
    await query.message.reply_text(reply)


async def on_offers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # The agent may take seconds; deciding off the event loop keeps other chats answered meanwhile.
    chat_id = update.effective_chat.id
    try:
        reply = await asyncio.to_thread(_request_offer, _db(context), chat_id, _directory(context))
    except sqlite3.OperationalError as exc:
        log.warning("/offers from chat %s failed: %s", chat_id, exc)
        reply = BUSY
    await update.effective_message.reply_text(reply)


def _request_offer(db_path, chat_id: int, directory: Path) -> str:
    conn = connect(db_path)
    try:
        return request_offer(conn, chat_id, directory)
    finally:
        conn.close()


async def on_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = connect(_db(context))
    try:
        reply = whoami(conn, update.effective_chat.id, _directory(context))
    finally:
        conn.close()
    await update.effective_message.reply_text(reply)


def register(app: Application) -> None:
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(START_PATTERN), on_start))
    app.add_handler(CallbackQueryHandler(on_pick, pattern=PICK_PATTERN))
    app.add_handler(CommandHandler("offers", on_offers))
    app.add_handler(CommandHandler("whoami", on_whoami))
    app.add_handler(CommandHandler("switch", on_switch))
