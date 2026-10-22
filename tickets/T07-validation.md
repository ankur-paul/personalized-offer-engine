# T07 — Validation with the rule-breaking property test (test-first)
**Status:** DONE
**Prereqs:** T06 · **Branch:** t07-validation

## Goal
Every proposed Offer is re-checked against every Rule before it can be sent, and a property test shows random
rule-breaking proposals never pass. M2 (PLAN §3.5 step 3, §7; ADR 0001). Written test-first.

## Scope / files
- `src/offer_engine/validation.py`:
  `validate(proposal: Proposal, state: CustomerState, rules: RuleSet, budget: BudgetState, now: datetime,
  catalog: Catalog, caption_checker: Callable[[str, Proposal, Catalog], list[str]] = no_caption_check) -> ValidationResult`.
  T11 passes the real Caption Check from T08.

## Details
- Recompute `eligible_set` itself; never trust an Eligible Set handed in by the chooser.
- No Offer (`offer_type is None`) is always valid.
- Failures, each a short code plus detail (e.g. `param_out_of_range: pct=25 > 20 (max_pct_by_loyalty_tier)`):
  short-circuit present (opt-out, holdout, fatigue, cap, cooldown, eligibility); Offer Type not in the Eligible
  Set; category not an option for that type; any param missing, extra, or outside its range; cost over the cost
  cap or remaining budget; `send_at` outside `send_window`; featured products unknown, not in the chosen category,
  or not in the Customer's own events of the last 90 days; more than 2 featured products; empty or missing
  caption/reason; plus whatever `caption_checker` returns.
- Report **all** failures, not just the first.

Done as built:
- Each failure reads `code: detail (rule)`. The bracket names the Rule broken, e.g.
  `short_circuit: holdout (holdout_pct)` or `over_budget: ₹300 > ₹200 left (weekly_budget)`. A value below a range
  says `(minimum)`, except `min_basket`, which says `(margin_floor_pct)`.
- A short-circuit replaces the Offer Type, param, cost and send-time checks, which have no Eligible Set to check
  against. The featured-product, caption and reason checks still run.
- Only `pct_category` takes a category. Any other Offer Type with a category fails `category_not_eligible`. Its
  featured products only need to be in the Customer's own events of the last 90 days.
- `send_at=None` on an Offer fails `send_at_missing`. It does not mean "send now", so a chooser sets the time.
  A send time outside the window names `in the past`, `max_send_delay_hours`, `send_hour_start`, `send_hour_end`
  or `send_window` (allowed hours on a later day; only the first allowed span is open).
- Cost is the worst case in both budget modes, with ₹0.000001 of slack for float rounding at the top of a range.
- Params that are NaN or infinite fail `param_out_of_range`. Without that check, NaN would pass every comparison.
- The property test runs short-circuit, Offer Type, category, budget and cost-cap mutations alone, because each one
  reshapes the whole Eligible Set. It combines the others, one per part of the proposal. `--hypothesis-show-statistics`
  lists how often each mutation ran. Disabling any one check in `validate` makes it fail.

## Tests (write first)
- `tests/test_validation.py`: a valid proposal passes; one test per failure code.
- `tests/test_validation_property.py` (hypothesis): generate a valid proposal from a random fixture Customer and
  Eligible Set, then apply one or more random mutations from a catalogue where each mutation breaks a named Rule
  (raise a param above its bound, pick a category not in the set, push `send_at` outside the window, feature a
  product the Customer never saw, exceed the budget, propose for an opted-out or Holdout Customer, …). Assert
  `ok is False` and the broken Rule appears in `failures`. Also assert unmutated valid proposals pass.
  At least 500 examples per run.

## Check
`uv run pytest tests/test_validation.py tests/test_validation_property.py -q` → green, hypothesis reports ≥500
examples.

## Done when
- [x] `validate` re-derives the Eligible Set and checks every Rule in Details
- [x] Property test with ≥500 examples shows no rule-breaking proposal passes
- [x] PROGRESS.md line added; `uv run pytest` green
- [x] Committed: `T07: Validation and rule-breaking property test`
