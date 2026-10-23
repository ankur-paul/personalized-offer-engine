from dataclasses import fields

from console.rule_labels import BLANK, GROUPS, LABELS, sentence
from offer_engine.domain import BudgetMode, RuleSet


def test_every_rule_field_is_one_blank_in_exactly_one_label():
    labelled = [field for label in LABELS for field in label.fields]
    assert sorted(labelled) == sorted(f.name for f in fields(RuleSet))
    for label in LABELS:
        assert label.text.count(BLANK) == len(label.fields), label.text
        assert label.group in GROUPS


def test_sentence_fills_the_other_blanks():
    label = next(label for label in LABELS if "frequency_cap_count" in label.fields)
    values = {"frequency_cap_count": 2, "frequency_cap_days": 7}
    assert sentence(label, values) == "Send at most 2 offers per 7 days"
    assert sentence(label, values, blank="frequency_cap_count") == "Send at most __ offers per 7 days"
    assert sentence(label, values, blank="frequency_cap_days") == "Send at most 2 offers per __ days"


def test_sentence_names_the_key_and_the_budget_mode():
    by_field = {label.fields[0]: label for label in LABELS}
    assert sentence(by_field["max_pct_by_category"], {}, blank="max_pct_by_category", key="fashion") == (
        "Give at most __% off fashion"
    )
    assert sentence(by_field["budget_mode"], {"budget_mode": BudgetMode.WORST_CASE}) == (
        "Reserve budget at worst-case cost"
    )
    assert (
        sentence(by_field["weekly_budget"], {"weekly_budget": 50_000.0})
        == "Spend at most ₹50,000 a week on offers"
    )
