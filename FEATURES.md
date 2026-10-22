# Features

What the app does now. Edit in place when a change alters what users see or can do.

## What it does

- `offer-engine check-env` lists each `.env` key as `set` or `missing`, never its value. It exits 1 when `OFFER_BOT_TOKEN`, `OFFER_BOT_USERNAME` or `ANTHROPIC_API_KEY` is missing or `CUSTOMER_BOTS` is malformed.

## Known limits

- The CLI has one command so far. Nothing decides or sends Offers yet.
