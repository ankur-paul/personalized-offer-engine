"""The Customer Bot simulator process: `python -m offer_engine.customer_sim.app`, polling.

T04 runs only the first Customer Bot in `CUSTOMER_BOTS`. On an Offer Card from the Offer Bot it replies
`/claim CODE` to the Offer Bot by username, once per code.
"""

from __future__ import annotations

import logging
import re

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from offer_engine.config import Settings

log = logging.getLogger(__name__)

CODE_PATTERN = re.compile(r"\bPOE-[A-Z0-9]{6}\b", re.IGNORECASE)


def parse_code(caption: str | None) -> str | None:
    """The first Offer code in a caption, uppercased, or None."""
    match = CODE_PATTERN.search(caption or "")
    return match.group(0).upper() if match else None


def build_app(settings: Settings) -> Application:
    if not settings.customer_bots:
        raise SystemExit("CUSTOMER_BOTS is empty; run `offer-engine setup`")
    if not settings.offer_bot_username:
        raise SystemExit("OFFER_BOT_USERNAME is missing; run `offer-engine setup`")
    username, token = settings.customer_bots[0]
    offer_bot = settings.offer_bot_username.lstrip("@")
    app = Application.builder().token(token).build()
    # Telegram asks bot-to-bot handlers to terminate predictably: claim each code once, ignore everything else.
    claimed: set[str] = set()

    async def on_offer_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        code = parse_code(update.effective_message.caption)
        if code is None or code in claimed:
            log.info("@%s: Offer Card without a new code; not replying", username)
            return
        claimed.add(code)
        await context.bot.send_message(f"@{offer_bot}", f"/claim {code}")
        log.info("@%s: sent /claim %s to @%s", username, code, offer_bot)

    async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.info("@%s: @%s says %r", username, offer_bot, update.effective_message.text)

    from_offer_bot = filters.User(username=offer_bot)
    app.add_handler(MessageHandler(filters.PHOTO & from_offer_bot, on_offer_card))
    app.add_handler(MessageHandler(filters.TEXT & from_offer_bot, on_text))
    log.info("running Customer Bot @%s", username)
    return app


def main() -> None:
    from offer_engine.bot_logging import configure_logging
    from offer_engine.config import load_settings

    configure_logging()
    settings = load_settings()
    if not settings.customer_bots:
        # Exit cleanly so `offer-engine start` keeps the Offer Bot running for Testers.
        log.warning("CUSTOMER_BOTS is empty; no Customer Bot to run")
        return
    build_app(settings).run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
