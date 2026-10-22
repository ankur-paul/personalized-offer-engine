# T31 — Stretch: Campaigns
**Status:** TODO
**Prereqs:** T22 · **Branch:** t31-campaigns

## Goal
*Stretch:* a marketer defines a named range of simulated dates that temporarily changes named Rules, and may loosen
them (e.g. a Diwali sale raising the max discount). M7 (PLAN §3.3; GLOSSARY "Campaign").

## Scope / files
- `src/offer_engine/schema/t31_campaigns.sql`: `campaigns(id, name, starts_at, ends_at, overrides_json, author,
  created_at)`.
- `src/offer_engine/rules_store.py`: add `effective_rules(conn, now) -> tuple[int, RuleSet, str | None]`: current
  version with every active Campaign's overrides applied (overlapping Campaigns: strictest wins per field, except
  that a Campaign may loosen the base). Returns the Campaign name.
- `src/offer_engine/pipeline.py`: load Rules via `effective_rules`; when a Campaign field is the Binding Rule,
  record it as `campaign:<name>:<field>`. Change only
  the line that loads the Rules: T26 may be adding a `validate` keyword to `decide` in parallel.
- `console/pages/5_campaigns.py`: list, create (name, dates, Rule fields to override with plain-English labels from
  `rule_labels.py`), delete future Campaigns.

## Tests
- `tests/test_campaigns.py`: overrides apply only inside the date range; loosening works; overlapping Campaigns;
  Binding Rule names the Campaign; Validation uses the same effective Rules as the Eligible Set.

## Check
Create "Year-end sale" for the next 3 simulated days raising fashion max discount to 30%; advance a day → fashion
Offers above the old cap appear with Binding Rule `campaign:Year-end sale:max_pct_by_category`; after the range
they stop.

## Done when
- [ ] Campaigns change named Rules only inside their simulated date range
- [ ] Decisions name the Campaign when it binds
- [ ] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [ ] Committed: `T31: Campaigns`
