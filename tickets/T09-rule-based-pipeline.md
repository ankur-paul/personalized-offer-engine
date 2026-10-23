# T09 — Rule-based decision pipeline, Decision log, cart-abandoned Trigger
**Status:** DONE
**Prereqs:** T05, T07 · **Branch:** t09-pipeline

## Goal
`offer-engine trigger cart-abandoned C00042` runs the full pipeline (Rules → rules chooser → Validation → log) and
prints the Decision with its Binding Rule; an Offer is queued if one was chosen. M2 slice "cart-abandoned Trigger →
rule-based Offer" (PLAN §3.5, §8; "Assumed › Deciding").

## Scope / files
- `src/offer_engine/customers.py`: `load_customer_state(conn, customer_id, now) -> CustomerState` and
  `load_customer_states(conn, ids, now) -> dict[str, CustomerState]` (bulk, for the Daily Sweep).
- `src/offer_engine/budget.py`: `budget_state(conn, rules, now) -> BudgetState`; week starts Monday 00:00
  simulated; `reserved` sums outstanding Offers (`queued`, `sent`, `claimed`) at worst-case or expected cost per
  `budget_mode`; `spent` sums redeemed Offers' actual cost this week.
- `src/offer_engine/choosers/__init__.py`, `choosers/priors.py` (fixed Lift prior per Offer Type),
  `choosers/rules_chooser.py`: `choose(eligible: EligibleSet, state, catalog, rules) -> Proposal`. Picks the option
  and parameters maximising Estimated Lift × expected margin − expected cost (lift from
  `option.estimated_lift`, else the prior); No Offer if nothing is positive. Featured products: up to 2 the
  Customer viewed or carted in the chosen category. Caption from a template per Offer Type with **no numbers**,
  e.g. `"Still thinking about {product}? Here's something to help."`. `send_at` = start of `send_window`.
- `src/offer_engine/pipeline.py`:
  - `decide(conn, customer_id, trigger: TriggerKind, now, *, chooser=None, lift_estimator=None) -> Decision`
  - `default_chooser(state) -> Callable` returns the rules chooser (T11 changes this function only).
  - `default_lift_estimator() -> Callable[[CustomerState, EligibleOption], float | None]` returns "no estimate"
    (T16 changes this function only).
  - Steps: load state, rules version, budget → `eligible_set` → fill `estimated_lift` per option → chooser →
    `validate` → on failure or exception, rules chooser as Fallback (`chooser=fallback`); if the Fallback's own
    proposal fails Validation, log No Offer with `binding_rule="fallback_failed"` (a bug signal) → write
    `decisions` row; if an Offer: write `offers` row (`queued`, code `POE-XXXXXX`, `expires_at = send_at +
    offer_validity_days`, costs, `rule_version`, `source=live`).
  - Chooser recorded: `rules` when `default_chooser` gave the rules chooser, `agent`/`fallback` once T11 lands.
- `src/offer_engine/commands/trigger.py`: `offer-engine trigger cart-abandoned CUSTOMER_ID` inserts a
  `cart_abandoned` event at clock now (product from the Customer's latest `add_to_cart`, or any viewed product)
  then calls `decide`; prints the Decision.
- `src/offer_engine/commands/decisions.py`: `offer-engine decisions --last 10 [--customer ID]`.
- Extend `commands/eligible.py` with `--customer ID` now that the loader exists.

## Details
- `default_chooser` and `default_lift_estimator` are separate functions on purpose: T11 and T16 may run in
  parallel and each edits only its own function.
- The pipeline modules never read `sim_*` tables (boundary test from T02).
- Done as built: the Holdout Decision's Binding Rule is `holdout_pct`, the name the Rules engine records, not `holdout`.
- Done as built: a Decision's Binding Rule is the limit on the Offer's main parameter (`pct`, `amount` or `multiplier`). Free shipping and the Nudge have none. The Check on seed 7 gives `pct_category beauty pct=8 cap=70 · chooser=rules · binding: max_pct_by_loyalty_tier · rule v0 · valid` for C00042.
- Done as built: the rules chooser tries a grid (whole percents, ₹50 flat steps, 0.5× multipliers). Lift follows the Ground Truth curve `max Lift · (1 − e^(−depth/k))` with `max Lift` and `k` from `priors.py`. An `estimated_lift` replaces the prior's max Lift and keeps its shape. The `cap` equals the expected discount on the category's average basket, rounded up to ₹10 and clamped to its range. Expected cost = (0.10 base chance + Lift) × cost if redeemed.
- Done as built: when the rules chooser is the primary chooser and fails Validation, it is not run again; the Decision is `fallback_failed` with `chooser=rules`. A Decision's `validation` is None when nothing was proposed or rejected. Otherwise `ok` is whether the logged Offer passed, and `failures` keeps the rejected proposal's failures (or `chooser_error: …`).
- Done as built: `reserved` leaves out Offers past `expires_at` and non-live Offers. `spent` takes the basket from the `order` event linked by `offer_id`, else the worst-case cost.
- Done as built: `tests/conftest.py` has `world_template` (a generated 50-Customer world built once per session) and `world` (a private copy per test).

## Tests
- `tests/test_pipeline.py` on a 50-Customer generated fixture DB: Holdout Customer → No Offer, binding
  `holdout`; eligible Customer → `queued` Offer whose terms are inside the Eligible Set; a chooser returning an
  out-of-range proposal → `fallback` with the failures stored; a chooser raising → `fallback`; frequency cap
  reached after N triggers.
- `tests/test_budget.py`: reserved at worst case vs expected; week boundary.
- `tests/test_rules_chooser.py`: picks No Offer when every option has non-positive value; never puts digits in
  the caption.

## Check
`uv run offer-engine generate --customers 200 && uv run offer-engine trigger cart-abandoned C00042` →
`Decision: pct_category fashion pct=12 cap=250 · chooser=rules · binding: margin_floor_pct · rule v0 · valid`;
`uv run offer-engine decisions --last 5` lists it.

## Done when
- [x] `decide` runs Rules → chooser → Validation → Fallback → log, and queues Offers
- [x] `default_chooser` / `default_lift_estimator` exist as separate functions
- [x] `offer-engine trigger cart-abandoned` and `offer-engine decisions` work
- [x] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [x] Committed: `T09: rule-based decision pipeline and cart-abandoned Trigger`
