"""Logging for the bot processes."""

from __future__ import annotations

import logging


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx logs each request URL at INFO, and Telegram URLs contain the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # The delivery job runs every 5 s, and apscheduler logs each run at INFO.
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
