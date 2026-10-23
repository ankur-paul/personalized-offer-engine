"""`offer-engine demo-send`: the Offer Bot sends the demo Offer Card to the first Customer Bot by username."""

from __future__ import annotations

import argparse


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("demo-send", help="send the demo Offer Card to the first Customer Bot")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    import asyncio

    from telegram import Bot
    from telegram.error import TelegramError

    from offer_engine import clock
    from offer_engine.config import load_settings
    from offer_engine.db import connect, migrate
    from offer_engine.offer_bot.handlers.demo import send_demo_card

    settings = load_settings()
    if not settings.offer_bot_token or not settings.customer_bots:
        print("error: OFFER_BOT_TOKEN and CUSTOMER_BOTS must be set; run `offer-engine setup`")
        return 1
    username = settings.customer_bots[0][0].lstrip("@")
    conn = connect(settings.db_path)
    migrate(conn)
    now = clock.now(conn)
    conn.close()

    async def send() -> None:
        async with Bot(settings.offer_bot_token) as bot:
            await send_demo_card(bot, f"@{username}", now)

    try:
        asyncio.run(send())
    except TelegramError as exc:
        print(f"error: Telegram refused the send to @{username}: {exc}")
        print("Check that Bot-to-Bot Communication Mode is on for both bots in @BotFather.")
        return 1
    print(f"sent the demo Offer Card to @{username}")
    return 0
