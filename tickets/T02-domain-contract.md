# T02 — Domain contract, SQLite store, Simulation Clock, rule versions
**Status:** TODO
**Prereqs:** T01 · **Branch:** t02-domain-contract

## Goal
Fix the shared types and core tables up front so the Rules, Validation, generator and bot tickets run in parallel
against them. `offer-engine clock show` / `clock advance` work. Contract ticket for the whole pass; PLAN §2.4, §3,
"Assumed"; GLOSSARY terms exactly.

## Scope / files
- `src/offer_engine/domain.py` (frozen dataclasses, `StrEnum`s):
  - `OfferType`: `pct_category`, `flat_above_min`, `free_shipping`, `points_multiplier`, `nudge`.
  - `TriggerKind`: `cart_abandoned`, `points_expiring`, `long_gap`, `first_order_delivered`, `daily_sweep`, `on_request`.
  - `OfferStatus`: `queued`, `sent`, `claimed`, `dismissed`, `redeemed`, `expired`, `withdrawn`.
  - `Chooser`: `agent`, `fallback`, `rules`.
  - `Category(name, margin_pct, avg_basket)`, `Product(id, name, category, price)`,
    `Catalog(categories: dict[str, Category], products: dict[str, Product])`, plus
    `load_catalog(conn) -> Catalog` in `db.py`.
  - `Customer(id, signup_at, city_tier, device, channel, loyalty_tier, points_balance, points_expire_at,
    opted_out, is_tester_copy, source_customer_id)`.
  - `Event(customer_id, at, kind, category, product_id, amount, offer_id)` (optional fields `None`).
  - `ChatLink(customer_id, chat_id, kind)` with kind `bot` | `tester`.
  - `PastOffer(id, offer_type, category, status, created_at, expires_at, redeemed_at)`.
  - `CustomerState(customer, events, offers, chat)`: everything the pipeline may know about one Customer at `now`
    (events from the last 180 days).
  - `BudgetState(week_start, spent, reserved)`.
  - `RuleSet`: every Rule setting with a default: `max_pct_by_category: dict[str, float]`,
    `max_pct_by_loyalty_tier: dict[str, float]`, `margin_floor_pct`, `max_flat_amount`, `max_points_multiplier`,
    `per_offer_cost_cap`, `weekly_budget`, `budget_mode` (`worst_case` | `expected`), `frequency_cap_count`,
    `frequency_cap_days`, `cooldown_days_after_redemption`, `min_days_since_signup`, `send_hour_start`,
    `send_hour_end`, `max_send_delay_hours`, `holdout_pct` (10), `fatigue_dismissals` (3), `fatigue_window_days`
    (14), `fatigue_pause_days` (14), `offer_validity_days` (3), `shipping_fee` (40), `point_value` (0.25),
    `long_gap_days` (45), `points_expiry_warning_days` (7). `to_dict()` / `from_dict()` for storage.
  - `ParamRange(lo, hi)`; `EligibleOption(offer_type, category, ranges: dict[str, ParamRange],
    binding_rules: dict[str, str], worst_case_cost, estimated_lift: float | None)`.
  - `EligibleSet(customer_id, at, options, send_window: tuple[datetime, datetime] | None, short_circuit: str | None,
    binding_rule: str | None, dropped: dict[str, str])`.
  - `Proposal(offer_type: OfferType | None, category, params: dict[str, float], featured_product_ids, send_at,
    caption, reason)`; `offer_type=None` is No Offer.
  - `Offer(id, code, customer_id, offer_type, category, params, featured_product_ids, created_at, send_at,
    expires_at, caption, rule_version, worst_case_cost, expected_cost, status, source)`; `source` is `live` |
    `history_random`.
  - `ValidationResult(ok, failures: tuple[str, ...])`.
  - `Decision(id, customer_id, at, trigger, chooser, offer_id, reason, binding_rule, rule_version, validation)`.
- `src/offer_engine/db.py`: `connect(path=None) -> sqlite3.Connection` (WAL mode, foreign keys, row factory),
  `migrate(conn)` applying `offer_engine/schema/*.sql` in name order, recording applied files in
  `schema_migrations`.
- `src/offer_engine/schema/t02_core.sql`: tables `categories`, `products`, `customers`, `events`, `chats`,
  `offers`, `decisions`, `rule_versions`, `clock`, matching the types above, with indexes on
  `events(customer_id, at)`, `offers(customer_id, status)`, `decisions(at)`.
- `src/offer_engine/clock.py`: `now(conn) -> datetime`, `set_now(conn, at)`, `advance(conn, hours) -> datetime`.
  Start time `2026-12-01T00:00` (history ends there). Naive datetimes, simulated IST.
- `src/offer_engine/rules_store.py`: `current_rules(conn) -> tuple[int, RuleSet]` (version 0 = defaults when the
  table is empty), `save_rules(conn, rules, author, note) -> int`, `list_versions(conn)`,
  `revert(conn, version, author) -> int` (saves a new version equal to the old one).
- Commands: `commands/db.py` (`offer-engine db init`), `commands/clock.py` (`clock show`,
  `clock advance --hours N | --days N`; T17 later makes advance run the world).
- `tests/test_ground_truth_boundary.py`: AST-scans the pipeline modules listed in PLAN "Assumed › Code layout"
  (those that exist) and fails if any imports `offer_engine.sim` or contains a string matching `\bsim_\w+`.

## Details
- Types only: no business logic beyond (de)serialisation. Keep every field later tickets name; add nothing else.
- Money is `float` rupees; percentages are `float` 0–100.
- Default RuleSet values: pick sensible ones (e.g. margin floor 5%, weekly budget ₹50,000, frequency cap 2 per 7
  days, send hours 9–21). Categories come from T05; `max_pct_by_category` defaults to an empty dict meaning no
  per-category cap beyond the margin floor.

## Tests
- `tests/test_domain.py`: `RuleSet` round-trips through `to_dict`/`from_dict`; enums have the listed values.
- `tests/test_db.py`: `migrate` is idempotent; a second schema file in a temp dir applies after `t02_core.sql`.
- `tests/test_clock.py`: default start, `advance` by hours and days, persists across connections.
- `tests/test_rules_store.py`: defaults at version 0; save → version 1; revert creates version 3 equal to 1.
- `tests/test_ground_truth_boundary.py`: passes now; a fixture module importing `offer_engine.sim` fails it.

## Check
`uv run offer-engine db init && uv run offer-engine clock show && uv run offer-engine clock advance --days 1 && uv run offer-engine clock show`
→ `2026-12-01 00:00` then `2026-12-02 00:00`.

## Done when
- [ ] `domain.py` defines every type listed in Scope
- [ ] `clock advance --days 1` moves the stored simulated time by 24 hours
- [ ] `rules_store` saves, lists and reverts versions
- [ ] Ground Truth boundary test exists and passes
- [ ] PROGRESS.md line added; `uv run pytest` green
- [ ] Committed: `T02: domain contract, SQLite store, Simulation Clock`
