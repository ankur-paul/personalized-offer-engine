# T08 — Caption Check with adversarial bad-caption set (test-first)
**Status:** TODO
**Prereqs:** T02 · **Branch:** t08-caption-check

## Goal
An agent-written caption that contradicts or adds to the Offer's terms, invents urgency, or is too long is
rejected with reasons. M3 (PLAN §3.5 step 3; ADR 0005; GLOSSARY "Caption Check"). Written test-first.

## Scope / files
- `src/offer_engine/caption_check.py`: `check(caption: str, proposal: Proposal, catalog: Catalog) -> list[str]`
  (empty list = pass). Signature matches T07's `caption_checker`.
- `src/offer_engine/commands/caption_check.py`: `offer-engine caption-check "TEXT" --offer-type pct_category
  --param pct=15 --param cap=300 --category fashion` prints `PASS` or each reason.
- `tests/data/captions.jsonl`: one case per line `{caption, offer, expect: "pass" | [reason codes]}`.

## Details
Reason codes:
- `number_mismatch`: any number, ₹ amount, percentage or multiplier ("2x") that isn't one of the Offer's own
  terms (pct, cap, amount, min basket, multiplier, validity days). Handle `₹1,499`, `Rs 1499`, `1.5k`, `20 %`,
  number words ("twenty percent").
- `deadline_mismatch`: dates, weekdays or times; "tonight", "today only", "midnight", "in N hours".
- `invented_urgency`: "last chance", "hurry", "only a few left", "selling out", "before it's gone", etc.
- `unoffered_promise`: "free gift", "cashback", "guaranteed", "free delivery" or "free shipping" unless the Offer
  Type is `free_shipping`, "extra/additional discount", "no minimum" when there is one.
- `too_long`: over 280 characters. `empty`: blank after trimming.
- Captions may mention the category, featured products and the Customer's own context without numbers.
- Keep the matcher simple and table-driven so the adversarial file grows without code changes.

## Tests (write first)
`tests/test_caption_check.py` runs every case in `captions.jsonl`: at least 40 bad captions (covering every
reason code, Hinglish and emoji variants, numbers spelled out, prices of featured products) and at least 15 good
ones that must pass.

## Check
`uv run offer-engine caption-check "Hurry, 30% off tonight only!" --offer-type pct_category --param pct=15 --param cap=300 --category fashion`
→ `number_mismatch`, `deadline_mismatch`, `invented_urgency`.

## Done when
- [ ] `check` returns the reason codes in Details
- [ ] `captions.jsonl` has ≥40 bad and ≥15 good cases, all passing the test
- [ ] `offer-engine caption-check` prints reasons
- [ ] PROGRESS.md line added; `uv run pytest` green
- [ ] Committed: `T08: Caption Check with adversarial captions`
