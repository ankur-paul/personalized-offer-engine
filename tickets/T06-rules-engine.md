# T06 — Rules engine: Eligible Set with Binding Rules (test-first)
**Status:** IN PROGRESS
**Prereqs:** T02 · **Branch:** t06-rules-engine

## Goal
A pure function computes the Eligible Set for one Customer at one moment, records the Binding Rule for every
limit, and short-circuits Holdout, Opt-out and Fatigue Pause to No Offer. M2 (PLAN §3.3, §3.5 step 1, §4.4;
ADR 0001). Written test-first (CLAUDE.md › Testing).

## Scope / files
- `src/offer_engine/rules.py`:
  - `eligible_set(state: CustomerState, rules: RuleSet, budget: BudgetState, now: datetime, catalog: Catalog) -> EligibleSet`
  - `in_holdout(customer_id: str, holdout_pct: float) -> bool`: SHA-256 of the **source** Customer ID (strip a
    Tester-copy suffix `-t<digits>`), first 8 bytes mod 10,000 < pct × 100.
  - `fatigue_paused_until(state, rules) -> datetime | None`.
  - `offer_cost(offer_type, category, params, catalog, rules) -> tuple[float, float]` (worst case, expected
    before the Redemption chance), using the cost model in PLAN "Assumed › Deciding".
- `src/offer_engine/commands/eligible.py`: `offer-engine eligible --demo` (built-in fixture Customer) and
  `--customer ID` (loads from DB once T09 adds the loader; until then `--demo` only). Prints each option, its
  ranges, and the Binding Rule per limit.

## Details
Order of checks (first hit short-circuits, recorded as `short_circuit` and `binding_rule`):
1. Opt-out (`customer.opted_out`) → `opt_out`. Absolute.
2. Holdout → `holdout`.
3. Fatigue Pause: `fatigue_dismissals` `dismissed` Offers within `fatigue_window_days` → paused for
   `fatigue_pause_days` from the last one → `fatigue_pause`.
4. Frequency cap (`frequency_cap_count` Offers created within `frequency_cap_days`) → `frequency_cap`.
5. Cooldown after Redemption → `cooldown`.
6. Eligibility: `min_days_since_signup` → `eligibility`.

Then per Offer Type build options; **strictest wins**: every upper bound is the min of all Rules that bound it,
and `binding_rules[param]` names the Rule that gave the min:
- `pct_category`: one option per category in the Customer's events of the last 90 days. `pct` upper bound =
  min(`max_pct_by_category[cat]`, `max_pct_by_loyalty_tier[tier]`, category margin − `margin_floor_pct`); `cap`
  upper bound = min(`per_offer_cost_cap`, remaining budget). Lower bound for `pct` is 5.
- `flat_above_min`: `amount` ≤ min(`max_flat_amount`, `per_offer_cost_cap`, remaining budget); `min_basket` ≥
  amount / ((avg margin − floor)/100) so the margin floor holds on the minimum basket.
- `free_shipping`: allowed if `shipping_fee` ≤ cost cap and remaining budget.
- `points_multiplier`: `multiplier` in [1.5, `max_points_multiplier`], cost check as above.
- `nudge`: always present unless short-circuited.
- Remaining budget = `weekly_budget − spent − reserved` (BudgetState already counts reserved at worst case or
  expected, per `budget_mode`). An option whose range is empty is left out and listed in `dropped` with its Rule.
- `send_window`: from `now` to `now + max_send_delay_hours`, clipped to `send_hour_start`–`send_hour_end`; `None`
  if no allowed hour remains.

## Tests (write first)
`tests/test_rules.py`: one test per Rule above, showing it binds and is named; conflict tests where two Rules bound
the same parameter and the stricter wins; Opt-out beats everything; Holdout deterministic, ~10% ±1% over 10,000
IDs, Tester copy shares its source's Holdout; empty range is dropped with its Rule; Nudge survives a zero budget;
`send_window` clipping at the end of the day.

## Check
`uv run offer-engine eligible --demo` → table of options with ranges and a Binding Rule per limit, e.g.
`pct_category fashion  pct 5–20  (binding: max_pct_by_loyalty_tier)`.

## Done when
- [ ] `eligible_set` implements every Rule in Details, each naming itself as Binding Rule
- [ ] `in_holdout` is hash-based and shared by Tester copies
- [ ] `offer-engine eligible --demo` prints the Eligible Set
- [ ] PROGRESS.md line added; `uv run pytest` green
- [ ] Committed: `T06: Rules engine with Binding Rules`
