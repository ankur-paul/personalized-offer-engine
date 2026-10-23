# T22 — Console: Rule forms, versions, revert, budget mode, emergency withdraw
**Status:** DONE
**Prereqs:** T10, T21 · **Branch:** t22-console-rules

## Goal
A marketer edits Rules in plain-English forms, sees version history with who/when, reverts in one click, switches
Reserved Budget between worst-case and expected cost, and withdraws all outstanding Offers in an emergency. M5
(PLAN §3.3, §6; QnA Q13, Q19, Q23).

## Scope / files
- `console/rule_labels.py`: one plain-English label per `RuleSet` field, with the value as the blank, e.g.
  `"Never discount below __% margin"`, `"Send at most __ offers per __ days"`, `"Pause offers for __ days after
  __ 'Not now' taps within __ days"`, `"Keep __% of Customers in the Holdout"`.
- `console/pages/3_rules.py`: form with every field grouped (Discounts, Frequency, Budget, Timing, Fatigue,
  Holdout); **Your name** and **Note** required; **Save** → `rules_store.save_rules`; version history table (version,
  who, when, note, changed fields); **Revert to this version** per row.
- Budget mode radio: worst case (default) / expected cost; when expected, show a warning:
  `Expected-cost budgeting can overspend if more Offers are redeemed than predicted.` and the current
  worst-case exposure vs budget.
- `src/offer_engine/withdraw.py`: `withdraw_outstanding(conn, now, author) -> int`: every `queued`, `sent` or
  `claimed` Offer → `withdrawn`; outbox row for each chat-attached one: `This offer has been withdrawn: POE-…. Sorry for the change.`;
  logs who/when.
- **Withdraw outstanding Offers** button behind a confirmation checkbox.

## Details
- Rule changes apply to new Decisions only; Offers keep the `rule_version` they passed (already stored by T09).
- Changing `holdout_pct` changes who is in the Holdout: show a warning on that field.
- Leave space under the form for T28's **Preview impact** button.
- Done as built: labels with several blanks cover several fields ("Send at most __ offers per __ days"); each blank's input is labelled with the sentence, the other blanks filled with their saved values. `max_pct_by_category` and `max_pct_by_loyalty_tier` get one input per category or tier, blank for no cap. Version 0 (the defaults) is listed so it can be reverted to. Revert needs a name but no note, since `rules_store.revert` writes "revert to vN". Save also refuses a send window that doesn't start before it ends and saves nothing when nothing changed.
- Done as built: `withdraw_outstanding` skips past Offers (`source = 'past'`) and Offers past `expires_at`, which the day-step expires. It notifies only `sent` and `claimed` Offers' chats, since a queued card was never sent. "Logs who/when" is a `withdrawals` table (`t22_withdrawals.sql`) shown under the button. `count_outstanding` gives the count the page shows. `console_env` moved to `tests/console/conftest.py` to share it with the new page tests.

## Tests
- `tests/test_withdraw.py`: statuses changed, outbox rows only for chat-attached Customers, redeemed/expired
  untouched.
- `tests/console/test_rules_page.py` (AppTest): saving with a name creates a version; without a name shows an
  error; revert creates a new version; expected mode shows the warning.
- `tests/console/test_rule_labels.py`: every `RuleSet` field has a label.

## Check
Console › Rules: set margin floor 10% as "Asha" → version 1 listed with who/when; trigger a Decision → it records
rule version 1; **Revert** to 0 → version 2; tick confirm and **Withdraw** → outstanding Offers withdrawn and
Testers get the notice.

## Done when
- [x] Every Rule is editable with a plain-English label and versioned with who/when
- [x] One-click revert works
- [x] Budget mode toggle with overspend warning
- [x] Emergency withdraw marks Offers withdrawn and notifies chats
- [x] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [x] Committed: `T22: console Rule forms, versions and emergency withdraw`
