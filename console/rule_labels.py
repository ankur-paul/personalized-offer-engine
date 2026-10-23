"""Plain-English labels for the Rules page (PLAN §6): every RuleSet field is one blank `__` in exactly one label.
A label with several blanks lists its fields in blank order. `{key}` stands for the category or loyalty tier of a
per-key Rule (`max_pct_by_category`, `max_pct_by_loyalty_tier`)."""

from __future__ import annotations

from dataclasses import dataclass

BLANK = "__"
GROUPS = ("Discounts", "Frequency", "Budget", "Timing", "Fatigue", "Holdout")


@dataclass(frozen=True)
class RuleLabel:
    group: str
    text: str
    fields: tuple[str, ...]
    help: str = ""


LABELS = (
    RuleLabel("Discounts", "Never discount below __% margin", ("margin_floor_pct",)),
    RuleLabel(
        "Discounts",
        "Give at most __% off {key}",
        ("max_pct_by_category",),
        "Leave blank for no cap beyond the margin floor.",
    ),
    RuleLabel(
        "Discounts",
        "Give {key} Customers at most __% off",
        ("max_pct_by_loyalty_tier",),
        "Leave blank for no cap.",
    ),
    RuleLabel("Discounts", "Take at most ₹__ off a basket", ("max_flat_amount",)),
    RuleLabel("Discounts", "Multiply points by at most __×", ("max_points_multiplier",)),
    RuleLabel("Discounts", "Count free shipping as costing ₹__", ("shipping_fee",)),
    RuleLabel("Discounts", "Count each point as costing ₹__", ("point_value",)),
    RuleLabel(
        "Frequency", "Send at most __ offers per __ days", ("frequency_cap_count", "frequency_cap_days")
    ),
    RuleLabel(
        "Frequency",
        "Wait __ days after a Redemption before the next offer",
        ("cooldown_days_after_redemption",),
    ),
    RuleLabel("Frequency", "Wait __ days after signup before the first offer", ("min_days_since_signup",)),
    RuleLabel("Budget", "Spend at most ₹__ a week on offers", ("weekly_budget",)),
    RuleLabel("Budget", "Let one offer cost at most ₹__", ("per_offer_cost_cap",)),
    RuleLabel("Budget", "Reserve budget at __ cost", ("budget_mode",)),
    RuleLabel("Timing", "Send offers only between __:00 and __:00", ("send_hour_start", "send_hour_end")),
    RuleLabel("Timing", "Send an offer at most __ hours after deciding it", ("max_send_delay_hours",)),
    RuleLabel("Timing", "Keep each offer valid for __ days", ("offer_validity_days",)),
    RuleLabel("Timing", "Treat __ days without an order as a long gap", ("long_gap_days",)),
    RuleLabel(
        "Timing", "Remind Customers __ days before their points expire", ("points_expiry_warning_days",)
    ),
    RuleLabel(
        "Fatigue",
        "Pause offers for __ days after __ 'Not now' taps within __ days",
        ("fatigue_pause_days", "fatigue_dismissals", "fatigue_window_days"),
    ),
    RuleLabel("Holdout", "Keep __% of Customers in the Holdout", ("holdout_pct",)),
)

BUDGET_MODE_NAMES = {"worst_case": "worst-case", "expected": "expected"}


def sentence(label: RuleLabel, values: dict[str, object], blank: str | None = None, key: str = "") -> str:
    """The label with each field's value filled in, except `blank`'s, which stays `__`."""
    parts = label.text.format(key=key).split(BLANK)
    out = parts[0]
    for field, part in zip(label.fields, parts[1:], strict=True):
        out += (BLANK if field == blank else _show(values[field])) + part
    return out


def _show(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return f"{value:,.0f}"
    return BUDGET_MODE_NAMES.get(str(value), f"{value:,}" if isinstance(value, int | float) else str(value))
