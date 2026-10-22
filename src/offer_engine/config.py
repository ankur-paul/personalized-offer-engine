"""Settings read from `.env` (and the process environment, which wins)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

DEFAULT_ENV_FILE = Path(".env")
DEFAULT_DB_PATH = Path("data/offer_engine.db")
DEFAULT_SEED = 7

# Every key `.env.example` documents, in the order check-env prints them.
ENV_KEYS = (
    "OFFER_BOT_TOKEN",
    "OFFER_BOT_USERNAME",
    "CUSTOMER_BOTS",
    "ANTHROPIC_API_KEY",
    "OFFER_AGENT_MODEL",
    "FAST_AGENT_MODEL",
    "DB_PATH",
    "SEED",
    "CONSOLE_PASSWORD",
)
REQUIRED_KEYS = ("OFFER_BOT_TOKEN", "OFFER_BOT_USERNAME", "ANTHROPIC_API_KEY")


@dataclass(frozen=True)
class Settings:
    offer_bot_token: str | None = None
    offer_bot_username: str | None = None
    customer_bots: list[tuple[str, str]] = field(default_factory=list)
    anthropic_api_key: str | None = None
    offer_agent_model: str | None = None
    fast_agent_model: str | None = None
    db_path: Path = DEFAULT_DB_PATH
    seed: int = DEFAULT_SEED
    console_password: str | None = None


def read_env(env_file: Path | None = None) -> dict[str, str]:
    """Non-empty values of ENV_KEYS from the env file, overridden by the process environment."""
    path = env_file if env_file is not None else DEFAULT_ENV_FILE
    file_values = dotenv_values(path) if path.is_file() else {}
    values: dict[str, str] = {}
    for key in ENV_KEYS:
        value = os.environ.get(key) or file_values.get(key)
        if value and value.strip():
            values[key] = value.strip()
    return values


def parse_customer_bots(raw: str | None) -> list[tuple[str, str]]:
    """Parse `username1:token1,username2:token2`. Tokens contain a colon, so split on the first one only."""
    if not raw or not raw.strip():
        return []
    bots = []
    for i, entry in enumerate(raw.split(","), start=1):
        username, sep, token = entry.strip().partition(":")
        if not sep or not username.strip() or not token.strip():
            # Name the entry by position, never echo it: it may hold a token.
            raise ValueError(f"CUSTOMER_BOTS entry {i} is malformed; expected username:token")
        bots.append((username.strip(), token.strip()))
    return bots


def load_settings(env_file: Path | None = None) -> Settings:
    values = read_env(env_file)
    seed_raw = values.get("SEED")
    try:
        seed = int(seed_raw) if seed_raw else DEFAULT_SEED
    except ValueError:
        raise ValueError(f"SEED must be an integer, got {seed_raw!r}") from None
    return Settings(
        offer_bot_token=values.get("OFFER_BOT_TOKEN"),
        offer_bot_username=values.get("OFFER_BOT_USERNAME"),
        customer_bots=parse_customer_bots(values.get("CUSTOMER_BOTS")),
        anthropic_api_key=values.get("ANTHROPIC_API_KEY"),
        offer_agent_model=values.get("OFFER_AGENT_MODEL"),
        fast_agent_model=values.get("FAST_AGENT_MODEL"),
        db_path=Path(values["DB_PATH"]) if "DB_PATH" in values else DEFAULT_DB_PATH,
        seed=seed,
        console_password=values.get("CONSOLE_PASSWORD"),
    )
