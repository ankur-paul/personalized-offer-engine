"""Customer responses to Offer Cards: the Claim / Not now / Stop buttons, and the same actions as text commands
(`/claim CODE`, `/notnow CODE`, `/stop`) for Customer Bots."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters

from offer_engine.db import connect
from offer_engine.offer_bot import responses
from offer_engine.offer_bot.delivery import CLAIM, NOT_NOW, STOP

log = logging.getLogger(__name__)

# Text, not a command filter: whether a bot's private message gets a bot_command entity is undocumented.
CODE_COMMAND_PATTERN = r"(?i)^/(claim|notnow)(?:@\w+)?(?:\s+(\S+))?\s*$"
STOP_PATTERN = r"(?i)^/stop(?:@\w+)?\s*$"
BUTTON_PATTERN = rf"^(?:({CLAIM}|{NOT_NOW}):(\S+)|({STOP}))$"


def respond(db_path, action: str, code: str | None, chat_id: int) -> str:
    """Apply one action for `chat_id` and return the reply."""
    if action != STOP and not code:
        return f"Send /{action} followed by the code from the Offer Card, e.g. /{action} POE-AB12CD"
    conn = connect(db_path)
    try:
        if action == STOP:
            return responses.stop(conn, chat_id)
        if action == CLAIM:
            return responses.claim(conn, code, chat_id)
        return responses.dismiss(conn, code, chat_id)
    finally:
        conn.close()


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    match = context.matches[0]
    action, code = (match.group(1), match.group(2)) if match.group(1) else (STOP, None)
    reply = respond(context.bot_data["settings"].db_path, action, code, query.message.chat.id)
    log.info("button %s %s from chat %s: %s", action, code or "", query.message.chat.id, reply)
    # The database already changed, so the reply must go out even if these fail: a tap answered late (say, after
    # a restart) is "too old", and a second tap may find the buttons already gone.
    try:
        await query.answer()
    except TelegramError as exc:
        log.info("button tap not answered: %s", exc)
    try:
        # One tap per card; the code still works by text.
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError as exc:
        log.info("buttons not removed: %s", exc)
    await query.message.reply_text(reply)


async def on_code_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    match = context.matches[0]
    await _reply_text(update, context, match.group(1).lower(), match.group(2))


async def on_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply_text(update, context, STOP, None)


async def _reply_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE, action: str, code: str | None
) -> None:
    chat_id = update.effective_chat.id
    reply = respond(context.bot_data["settings"].db_path, action, code, chat_id)
    log.info("/%s %s from chat %s: %s", action, code or "", chat_id, reply)
    await update.effective_message.reply_text(reply)


def register(app: Application) -> None:
    app.add_handler(CallbackQueryHandler(on_button, pattern=BUTTON_PATTERN))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(CODE_COMMAND_PATTERN), on_code_command))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(STOP_PATTERN), on_stop))
