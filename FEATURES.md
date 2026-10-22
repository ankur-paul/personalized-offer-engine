# Features

What the app does now. Edit in place when a change alters what users see or can do.

## What it does

- `offer-engine check-env` lists each `.env` key as `set` or `missing`, never its value. It exits 1 when `OFFER_BOT_TOKEN`, `OFFER_BOT_USERNAME` or `ANTHROPIC_API_KEY` is missing or `CUSTOMER_BOTS` is malformed.
- `offer-engine setup` walks a developer through five steps: create the Offer Bot in BotFather, turn on Bot-to-Bot Communication Mode, create 6–8 Customer Bots, enter the Anthropic API key and model IDs, then check `.env`. It checks each bot token with Telegram `getMe`, reads tokens and the key hidden, never prints them, and saves `.env` with mode 0600 after each step. Running it again offers to keep each value already set.

## Known limits

- The CLI has two commands, `check-env` and `setup`. Nothing decides or sends Offers yet.
- `setup` does not ask for `DB_PATH`, `SEED` or `CONSOLE_PASSWORD`. Edit `.env` by hand to set them.
- The Bot-to-Bot menu path that `setup` prints has not been checked against BotFather.
