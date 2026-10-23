"""Interactive setup: walks a developer through creating the bots in BotFather and fills `.env`.

Secrets are read hidden and never printed back. `.env` is saved after each step, so a stopped run loses nothing;
running again offers to keep each value already there.
"""

from __future__ import annotations

import asyncio
import getpass
import os
import re
import tempfile
from pathlib import Path
from typing import Protocol

from dotenv import dotenv_values
from telegram import Bot
from telegram.error import TelegramError

from offer_engine.commands.check_env import report
from offer_engine.config import parse_customer_bots

STEPS = 5
MIN_CUSTOMER_BOTS, MAX_CUSTOMER_BOTS, DEFAULT_CUSTOMER_BOTS = 6, 8, 7
MODELS_DOCS_URL = "https://platform.claude.com/docs/en/about-claude/models/overview"
# The switch is only in BotFather's Mini App, not the /mybots text menu (checked by hand, 2026-10-23).
BOT_TO_BOT_PATH = (
    "tap Open to start the BotFather Mini App, pick @{username}, then turn on Bot-to-Bot Communication Mode"
)

# BotFather tokens look like `123456789:AAH...`; anything else is rejected without a network call.
_TOKEN_FORMAT = re.compile(r"^\d+:[A-Za-z0-9_-]{30,}$")
_KEY_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
_BARE_VALUE = re.compile(r"^[A-Za-z0-9_\-:.,@/+=]*$")


class WizardIO(Protocol):
    def say(self, text: str = "") -> None: ...
    def ask(self, prompt: str) -> str: ...
    def ask_secret(self, prompt: str) -> str: ...


class ConsoleIO:
    def say(self, text: str = "") -> None:
        print(text)

    def ask(self, prompt: str) -> str:
        return input(prompt)

    def ask_secret(self, prompt: str) -> str:
        return getpass.getpass(prompt)


def check_token(token: str) -> str | None:
    """The bot's username if Telegram's `getMe` accepts the token, else None (also when Telegram is unreachable)."""
    if not _TOKEN_FORMAT.match(token):
        return None

    async def get_username() -> str:
        async with Bot(token) as bot:
            return (await bot.get_me()).username

    try:
        return asyncio.run(get_username())
    except TelegramError:
        return None


def merge_env(env_path: Path, updates: dict[str, str]) -> None:
    """Set the given keys in place (appending new ones) and keep every other line; the file ends up mode 0600."""
    for key, value in updates.items():
        if "\n" in value or "\r" in value:
            raise ValueError(f"{key} must be a single line")
    lines = env_path.read_text().splitlines() if env_path.is_file() else []
    remaining = dict(updates)
    merged = []
    for line in lines:
        match = _KEY_LINE.match(line)
        if match and match.group(1) in updates:
            key = match.group(1)
            merged.append(f"{key}={_quote(updates[key])}")
            remaining.pop(key, None)
        else:
            merged.append(line)
    merged.extend(f"{key}={_quote(value)}" for key, value in remaining.items())
    _write_private(env_path, "".join(f"{line}\n" for line in merged))


def run_wizard(io: WizardIO, env_path: Path) -> None:
    example = env_path.with_name(".env.example")
    if not env_path.exists() and example.is_file():
        _write_private(env_path, example.read_text())
    existing = _existing_values(env_path)

    offer_username = _offer_bot_step(io, env_path, existing)
    _screen(io, 2, "Bot-to-Bot Communication Mode for the Offer Bot")
    io.say("The Offer Bot and every Customer Bot must have this mode on, or their private messages fail.")
    _bot_to_bot_reminder(io, offer_username)
    _customer_bots_step(io, env_path, existing)
    _anthropic_step(io, env_path, existing)

    _screen(io, 5, "Check .env")
    lines, ok = report(env_path)
    for line in lines:
        io.say(line)
    io.say()
    if ok:
        io.say(f"Setup complete. Saved to {env_path} (readable only by you).")
    else:
        io.say("Some required keys are still missing. Run `offer-engine setup` again to fill them.")


def _offer_bot_step(io: WizardIO, env_path: Path, existing: dict[str, str]) -> str:
    _screen(io, 1, "Offer Bot")
    token, username = existing.get("OFFER_BOT_TOKEN"), existing.get("OFFER_BOT_USERNAME")
    if token and username and _confirm(io, f"An Offer Bot is already set (@{username}). Keep it?"):
        return username
    io.say("Open https://t.me/BotFather in Telegram and send /newbot.")
    io.say("Any display name works (Customers see it); the username must end in 'bot'.")
    io.say("BotFather replies with a token like 123456789:AAH...")
    token, username = _ask_bot_token(io, "Offer Bot", used=_customer_tokens(existing))
    merge_env(env_path, {"OFFER_BOT_TOKEN": token, "OFFER_BOT_USERNAME": username})
    existing.update(OFFER_BOT_TOKEN=token, OFFER_BOT_USERNAME=username)
    return username


def _customer_bots_step(io: WizardIO, env_path: Path, existing: dict[str, str]) -> None:
    _screen(io, 3, "Customer Bots")
    try:
        bots = parse_customer_bots(existing.get("CUSTOMER_BOTS"))
    except ValueError:
        io.say("CUSTOMER_BOTS in .env is malformed; setting the Customer Bots up again.")
        bots = []
    if bots:
        names = ", ".join(f"@{username}" for username, _ in bots)
        if not _confirm(io, f"{len(bots)} Customer Bots are already set ({names}). Keep them?"):
            bots = []
        elif len(bots) >= MIN_CUSTOMER_BOTS:
            return

    io.say("Each Customer Bot plays one Customer and receives that Customer's Offers from the Offer Bot.")
    minimum, default = max(MIN_CUSTOMER_BOTS, len(bots)), max(DEFAULT_CUSTOMER_BOTS, len(bots))
    target = _ask_count(io, minimum=minimum, default=default)
    used = {existing["OFFER_BOT_TOKEN"]} | {token for _, token in bots}
    for number in range(len(bots) + 1, target + 1):
        _screen(io, 3, f"Customer Bot {number} of {target}")
        io.say("In @BotFather send /newbot again. Any name works; the username must end in 'bot'.")
        token, username = _ask_bot_token(io, f"Customer Bot {number}", used=used)
        used.add(token)
        _bot_to_bot_reminder(io, username)
        bots.append((username, token))
        # Saved after each bot so a stopped run keeps the ones already made.
        merge_env(env_path, {"CUSTOMER_BOTS": ",".join(f"{u}:{t}" for u, t in bots)})


def _anthropic_step(io: WizardIO, env_path: Path, existing: dict[str, str]) -> None:
    _screen(io, 4, "Claude API")
    updates = {}
    if not (
        existing.get("ANTHROPIC_API_KEY") and _confirm(io, "An Anthropic API key is already set. Keep it?")
    ):
        io.say("Create a key in the Claude Console (https://platform.claude.com), under API keys.")
        updates["ANTHROPIC_API_KEY"] = _ask_required(io, "Anthropic API key (hidden): ", secret=True)
    io.say(f"Look up current model IDs at {MODELS_DOCS_URL}")
    io.say(
        "(or ask Claude Code; its claude-api skill knows the current IDs). Press Enter to keep the value shown."
    )
    for key, role in (
        ("OFFER_AGENT_MODEL", "the offer agent; pick a strong model"),
        ("FAST_AGENT_MODEL", "Customer Bots and offline runs; pick a fast, cheap model"),
    ):
        current = existing.get(key)
        answer = io.ask(f"{key} ({role}){f' [{current}]' if current else ''}: ").strip()
        while not answer and not current:
            answer = io.ask(f"{key} is needed: ").strip()
        if answer:
            updates[key] = answer
    if updates:
        merge_env(env_path, updates)


def _ask_bot_token(io: WizardIO, label: str, used: set[str]) -> tuple[str, str]:
    while True:
        token = io.ask_secret(f"Paste the {label} token (hidden): ").strip()
        if not token:
            continue
        if token in used:
            io.say("That token belongs to a bot already set up here. Create a new bot and paste its token.")
            continue
        username = check_token(token)
        if username:
            io.say(f"Token OK: @{username}")
            return token, username
        io.say("Telegram did not accept that token, or could not be reached. Check it and paste it again.")


def _bot_to_bot_reminder(io: WizardIO, username: str) -> None:
    io.say(f"In @BotFather, {BOT_TO_BOT_PATH.format(username=username)}.")
    io.ask("Press Enter when it is on. ")


def _ask_count(io: WizardIO, minimum: int, default: int) -> int:
    while True:
        answer = io.ask(f"How many Customer Bots? ({minimum}-{MAX_CUSTOMER_BOTS}) [{default}]: ").strip()
        if not answer:
            return default
        if answer.isdigit() and minimum <= int(answer) <= MAX_CUSTOMER_BOTS:
            return int(answer)
        io.say(f"Enter a whole number from {minimum} to {MAX_CUSTOMER_BOTS}.")


def _ask_required(io: WizardIO, prompt: str, secret: bool = False) -> str:
    while True:
        answer = (io.ask_secret(prompt) if secret else io.ask(prompt)).strip()
        if answer:
            return answer


def _confirm(io: WizardIO, question: str) -> bool:
    while True:
        answer = io.ask(f"{question} [Y/n] ").strip().lower()
        if answer in ("", "y", "yes"):
            return True
        if answer in ("n", "no"):
            return False


def _screen(io: WizardIO, step: int, title: str) -> None:
    io.say()
    io.say(f"=== Step {step} of {STEPS}: {title} ===")


def _existing_values(env_path: Path) -> dict[str, str]:
    """Non-empty values in the env file itself; the process environment is ignored here."""
    if not env_path.is_file():
        return {}
    return {key: value.strip() for key, value in dotenv_values(env_path).items() if value and value.strip()}


def _customer_tokens(existing: dict[str, str]) -> set[str]:
    try:
        return {token for _, token in parse_customer_bots(existing.get("CUSTOMER_BOTS"))}
    except ValueError:
        return set()


def _quote(value: str) -> str:
    if _BARE_VALUE.match(value):
        return value
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _write_private(path: Path, text: str) -> None:
    """Write atomically through a temp file, which mkstemp creates with mode 0600."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as file:
            file.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
