"""`python -m offer_engine.live`: serve the live engine view on 0.0.0.0, port `LIVE_PORT` (default 8502)."""

from __future__ import annotations

import os

import uvicorn

from offer_engine.config import load_settings
from offer_engine.live.app import create_app

DEFAULT_PORT = 8502


def main() -> None:
    port = int(os.environ.get("LIVE_PORT") or DEFAULT_PORT)
    uvicorn.run(create_app(password=load_settings().console_password), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
