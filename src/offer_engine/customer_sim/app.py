"""The Customer Bot simulator process: `python -m offer_engine.customer_sim.app`, polling.

Every Customer Bot in `CUSTOMER_BOTS` runs here, one python-telegram-bot `Application` per token in one asyncio
loop. On an Offer Card from the Offer Bot, the bot plays its linked Customer (`roleplay.react_to_card`) and sends
the in-character reply with `/claim CODE` or `/notnow CODE` to the Offer Bot by username, once per Offer.
"""

from __future__ import annotations

import asyncio
import logging
import re
import signal
from typing import Any

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from offer_engine.commands.chats import bot_chat_ids
from offer_engine.config import Settings
from offer_engine.customer_sim import roleplay

log = logging.getLogger(__name__)

CODE_PATTERN = re.compile(r"\bPOE-[A-Z0-9]{6}\b", re.IGNORECASE)
AGENT_TIMEOUT_SECONDS = 30.0


def parse_code(caption: str | None) -> str | None:
    """The first Offer code in a caption, uppercased, or None."""
    match = CODE_PATTERN.search(caption or "")
    return match.group(0).upper() if match else None


def agent_client(settings: Settings) -> Any | None:
    """The role-play agent's client, or None (every Offer then gets the plain Ground Truth flip). Unless
    `AGENT_MODE` is `live` it is a `ReplayClient`, which in replay mode needs no key for a recorded answer; a
    missing one flips on Ground Truth alone."""
    if not settings.fast_agent_model or not (settings.anthropic_api_key or settings.agent_mode == "replay"):
        log.warning("ANTHROPIC_API_KEY or FAST_AGENT_MODEL unset; Customer Bots reply without the agent")
        return None
    real = None
    if settings.anthropic_api_key:
        import anthropic

        real = anthropic.Anthropic(
            api_key=settings.anthropic_api_key, max_retries=1, timeout=AGENT_TIMEOUT_SECONDS
        )
    if settings.agent_mode == "live":
        return real
    from offer_engine.demo.replay import ReplayClient

    return ReplayClient(real, settings.agent_mode)


def build_app(settings: Settings, username: str, token: str, client: Any | None) -> Application:
    if not settings.offer_bot_username:
        raise SystemExit("OFFER_BOT_USERNAME is missing; run `offer-engine setup`")
    offer_bot = settings.offer_bot_username.lstrip("@")
    chat_id = bot_chat_ids([(username, token)])[username.lstrip("@").lower()]
    app = Application.builder().token(token).build()

    async def on_offer_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        code = parse_code(update.effective_message.caption)
        if code is None:
            log.info("@%s: Offer Card without a code; not replying", username)
            return
        # Telegram asks bot-to-bot handlers to terminate predictably: the database allows one reaction per Offer.
        reaction = await asyncio.to_thread(
            roleplay.react_to_card,
            settings.db_path,
            code,
            chat_id,
            client,
            settings.fast_agent_model,
            settings.seed,
        )
        if reaction is None:
            log.info("@%s: %s isn't a new Offer for this bot; not replying", username, code)
            return
        await context.bot.send_message(f"@{offer_bot}", reaction.reply_text)
        log.info("@%s: %s → %s", username, code, reaction.reply_text.splitlines()[-1])

    async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.info("@%s: @%s says %r", username, offer_bot, update.effective_message.text)

    from_offer_bot = filters.User(username=offer_bot)
    app.add_handler(MessageHandler(filters.PHOTO & from_offer_bot, on_offer_card))
    app.add_handler(MessageHandler(filters.TEXT & from_offer_bot, on_text))
    return app


async def run_all(apps: list[tuple[str, Application]]) -> None:
    """Poll every bot until SIGINT or SIGTERM, then stop them all."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    started: list[Application] = []
    try:
        for username, app in apps:
            await app.initialize()
            await app.start()
            await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            started.append(app)
            log.info("running Customer Bot @%s", username)
        await stop.wait()
    finally:
        for app in reversed(started):
            await app.updater.stop()
            await app.stop()
            await app.shutdown()


def main() -> None:
    from offer_engine.bot_logging import configure_logging
    from offer_engine.config import load_settings

    configure_logging()
    settings = load_settings()
    if not settings.customer_bots:
        # Exit cleanly so `offer-engine start` keeps the Offer Bot running for Testers.
        log.warning("CUSTOMER_BOTS is empty; no Customer Bot to run")
        return
    client = agent_client(settings)
    apps = [
        (username, build_app(settings, username, token, client)) for username, token in settings.customer_bots
    ]
    asyncio.run(run_all(apps))


if __name__ == "__main__":
    main()
