"""The Offer Bot process: `python -m offer_engine.offer_bot.app`, polling."""

from __future__ import annotations

import importlib

from telegram import Update
from telegram.ext import Application

from offer_engine.config import Settings

# One entry per line, so tickets add or replace their own line without conflicting.
HANDLER_MODULES = [
    "offer_engine.offer_bot.handlers.demo",
]


def build_app(settings: Settings) -> Application:
    if not settings.offer_bot_token:
        raise SystemExit("OFFER_BOT_TOKEN is missing; run `offer-engine setup`")
    app = Application.builder().token(settings.offer_bot_token).build()
    app.bot_data["settings"] = settings
    for name in HANDLER_MODULES:
        importlib.import_module(name).register(app)
    return app


def main() -> None:
    from offer_engine.bot_logging import configure_logging
    from offer_engine.config import load_settings
    from offer_engine.db import connect, migrate

    configure_logging()
    settings = load_settings()
    conn = connect(settings.db_path)
    migrate(conn)
    conn.close()
    build_app(settings).run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
