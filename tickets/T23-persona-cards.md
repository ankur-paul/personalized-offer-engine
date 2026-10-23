# T23 — Persona Cards for the showcase Customers
**Status:** BLOCKED (needs human: review Persona Cards)
**Prereqs:** T13, T14 · **Branch:** t23-persona-cards

## Goal
6–8 showcase Customers are picked from the population, an agent drafts a Persona Card for each from observable
data, the user reviews them, and they are frozen in the repo so demos repeat. M5 (PLAN §4.2, QnA Q9, Q25).

## Scope / files
- `src/offer_engine/sim/personas/select.py`: `select_showcase(conn, rules) -> list[ShowcasePick]` with one Customer
  per case: `at_risk_high_value`, `new_one_order`, `deal_hunter`, `expiring_points`, `cart_abandoner`,
  `sure_thing` (Response Class `sure_thing`, should get No Offer), `holdout` (in the Holdout by `in_holdout`), plus
  one optional `persuadable`. Criteria are module constants; ties broken by ID for determinism.
- `src/offer_engine/sim/personas/draft.py`: `draft_card(client, model, profile_summary) -> PersonaCard`. The
  input is built **only** from observable data (profile, last 180 days of events, points); a fictional Indian name
  and a 60–100-word card in plain language (situation, needs, habits).
- `personas/<customer_id>.json`: `{customer_id, case, name, card, frozen, drafted_at}`.
- `src/offer_engine/commands/personas.py`: `personas draft` (writes drafts, skips frozen files),
  `personas show`, `personas freeze` (sets `frozen: true` on all after the user has reviewed/edited them).

## Details
- Cards never reveal Ground Truth: no "would buy anyway", no response class, no Lift (ADR 0002). The prompt
  builder takes a profile summary type with no `sim_*` fields, and the select step (which may read Ground Truth)
  passes only the Customer ID onward.
- Persona files depend on the default seed's Customer IDs (T05 determinism). Record the seed in each file.
- Review is a human step: after `personas draft`, set `**Status:** BLOCKED (needs human: review Persona Cards)`,
  tell the user, and finish after `personas freeze`.
- Model from `OFFER_AGENT_MODEL` (look up via the `claude-api` skill).
- Done as built: `draft_card` returns a `Draft(name, card)`. The command adds the case, `frozen`, `drafted_at`, `seed`
  and `population` (Customers in the world) and saves a `PersonaCard` from `src/offer_engine/personas.py`. That module
  also holds `CASES`, the case labels and `load_all()` for T24 and T25. It sits outside `sim/` so the Offer Bot can
  read the cards.
- Done as built: the criteria have bands so outliers stay out. Without them the Sure Thing and Holdout picks had
  over 200 and 99 orders in 180 days. Sure Thing and Holdout need 3–12 orders in 90 days, cart abandoner 2–8
  abandoned carts in 30 days, new one-order a signup 7–60 days ago. The five Offer cases skip the Holdout, Sure
  Things and Sleeping Dogs, and only the `holdout` case takes a Holdout Customer.
- Done as built: the first drafts were 7 women in their thirties out of 8, most of them school administrators, and
  3 ran over 100 words. Each call now sees the first sentence of the cards already written and must describe someone
  different. A card outside 60–100 words is asked for once more.
- Done as built: on a world that doesn't pick a frozen card's Customer, `draft` stops with an error. It deletes
  unfrozen drafts that aren't picked.

## Tests
- `tests/sim/test_persona_select.py`: on a seeded 10k fixture (or 2k if slow) every case gets a distinct Customer;
  the `holdout` pick is in the Holdout; the `sure_thing` pick has that class.
- `tests/test_persona_prompt.py`: the prompt builder's input type has no Ground Truth fields; a fake client's card
  is saved with `frozen: false`; `freeze` flips it; `draft` skips frozen files.

## Check
`uv run offer-engine personas draft && uv run offer-engine personas show` → 7–8 cards with names and cases; after
review `uv run offer-engine personas freeze` → files committed with `frozen: true`.

## Done when
- [x] One showcase Customer per case, including a Sure Thing and a Holdout Customer
- [ ] Persona Cards drafted from observable data only, reviewed by the user, frozen and committed
- [ ] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [ ] Committed: `T23: Persona Cards for showcase Customers`
