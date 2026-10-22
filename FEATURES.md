# Features

What the app does now. Edit in place when a change alters what users see or can do.

## What it does

- `offer-engine check-env` lists each `.env` key as `set` or `missing`, never its value. It exits 1 when `OFFER_BOT_TOKEN`, `OFFER_BOT_USERNAME` or `ANTHROPIC_API_KEY` is missing or `CUSTOMER_BOTS` is malformed.
- `offer-engine db init` creates the SQLite database at `DB_PATH` (default `data/offer_engine.db`) or applies new schema files. Running it again is safe.
- `offer-engine clock show` prints the simulated time, which starts at `2026-12-01 00:00`. `offer-engine clock advance --hours N` or `--days N` moves it forward. It never moves back.
- Rule settings are versioned in the database. Version 0 is the defaults, and a revert saves a new version equal to the old one. There is no command or console page for this yet.
- `offer-engine generate --customers N --months M --seed S` builds a fictional marketplace: 5 categories (margins 10–45%), 200 products in ₹, N Customers (IDs `C00001…` in signup order) and M months of events ending at the clock start (sessions, product views, carts, abandoned carts, orders, deliveries, returns and points). It prints counts per table and per event kind. The same seed gives the same database. Each run deletes the old world first, including Offers, Decisions and chat links.
- `offer-engine eligible --demo` prints the Eligible Set for a built-in Customer under the default Rules: each allowed Offer Type with its parameter ranges and the Binding Rule for each limit, the send window, and the options dropped with the Rule that emptied them.

## Known limits

- Nothing decides or sends Offers yet. Advancing the clock only moves the time; no events happen.
- History has no past Offers and no Ground Truth yet. 10k Customers would take over a minute to generate.
- `offer-engine eligible --customer ID` exits with an error until Customers can be loaded from the database (T09).
