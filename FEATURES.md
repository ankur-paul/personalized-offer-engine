# Features

What the app does now. Edit in place when a change alters what users see or can do.

## What it does

- `offer-engine check-env` lists each `.env` key as `set` or `missing`, never its value. It exits 1 when `OFFER_BOT_TOKEN`, `OFFER_BOT_USERNAME` or `ANTHROPIC_API_KEY` is missing or `CUSTOMER_BOTS` is malformed.
- `offer-engine db init` creates the SQLite database at `DB_PATH` (default `data/offer_engine.db`) or applies new schema files. Running it again is safe.
- `offer-engine clock show` prints the simulated time, which starts at `2026-12-01 00:00`. `offer-engine clock advance --hours N` or `--days N` moves it forward. It never moves back.
- Rule settings are versioned in the database. Version 0 is the defaults, and a revert saves a new version equal to the old one. There is no command or console page for this yet.
- `offer-engine start` runs the Offer Bot and the Customer Bot simulator together, prefixing each line of output with the process name. Ctrl-C stops both. If either exits with an error, both stop.
- Sending `/start` to the Offer Bot makes that chat the Tester for demo Customer `C00001` and sends a demo Offer Card: a PNG with "15% off Fashion", "Up to ₹300 off", the code `POE-DEMO01` and the expiry, plus a caption. `/claim POE-DEMO01` replies "Claimed POE-DEMO01. Show this code at checkout."
- `offer-engine demo-send` has the Offer Bot send the demo card to the first Customer Bot by `@username`. That bot replies `/claim POE-DEMO01`, and the Offer Bot acknowledges and logs the Claim.

## Known limits

- Nothing decides Offers yet; the only Offer the bots send is the hard-coded demo. Only the first Customer Bot in `CUSTOMER_BOTS` runs.
- The demo has no Claim / Not now / Stop buttons, and Claims are logged, not stored.
- Advancing the clock only moves the time; no events happen.
