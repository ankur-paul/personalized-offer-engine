"""Rules (PLAN §3.3, §6): every Rule as a plain-English form, versioned with who and when, one-click revert, the
budget mode, Preview impact of an edit, and the emergency withdraw of outstanding Offers. New Rules apply to new
Decisions only."""

from __future__ import annotations

from dataclasses import fields

import streamlit as st

from console import data
from console.rule_labels import BUDGET_MODE_NAMES, GROUPS, LABELS, RuleLabel, sentence
from offer_engine import clock, rules_store
from offer_engine.domain import LOYALTY_TIERS, BudgetMode, RuleSet
from offer_engine.sim.preview import Change, PreviewResult, preview
from offer_engine.withdraw import count_outstanding, list_withdrawals, withdraw_outstanding

PREFIX = "rule."
PCT_FIELDS = {"margin_floor_pct", "holdout_pct", "max_pct_by_category", "max_pct_by_loyalty_tier"}
LIMITS = {
    "send_hour_start": (0, 23),
    "send_hour_end": (1, 24),
    "max_points_multiplier": (1.0, None),
    "point_value": (0.0, None),
}
STEPS = {"point_value": 0.05, "max_points_multiplier": 0.5}
EXPECTED_WARNING = "Expected-cost budgeting can overspend if more Offers are redeemed than predicted."
HOLDOUT_WARNING = (
    "Changing this changes who is in the Holdout. Raising it holds back more Customers; lowering it starts sending "
    "Offers to Customers who were held back. Results from before and after the change aren't comparable."
)
DEFAULTS = RuleSet()


def reset_form() -> None:
    for key in [k for k in st.session_state if str(k).startswith(PREFIX)]:
        del st.session_state[key]


def finish(message: str) -> None:
    reset_form()
    st.session_state.rules_flash = message
    st.rerun()


def number(field: str, label: str, value: float | None, help: str = "") -> float | int | None:
    """One number input; ints stay ints. `value=None` gives an empty input (a per-key Rule with no cap)."""
    is_int = isinstance(getattr(DEFAULTS, field), int)
    low, high = LIMITS.get(field, (0, 100) if field in PCT_FIELDS else (0, None))
    if is_int:
        low, high = int(low), None if high is None else int(high)
    else:
        low, high = float(low), None if high is None else float(high)
    return st.number_input(
        label,
        min_value=low,
        max_value=high,
        value=value,
        step=1 if is_int else STEPS.get(field, 1.0),
        key=f"{PREFIX}{field}",
        help=help or None,
    )


def per_key(label: RuleLabel, keys: list[str], saved: dict[str, float]) -> dict[str, float]:
    field = label.fields[0]
    out = {}
    for column, key in zip(st.columns(len(keys)), keys, strict=True):
        with column:
            value = st.number_input(
                sentence(label, {}, blank=field, key=key),
                min_value=0.0,
                max_value=100.0,
                value=saved.get(key),
                step=1.0,
                key=f"{PREFIX}{field}.{key}",
                help=label.help or None,
            )
        if value is not None:
            out[key] = value
    return out


def rule_inputs(label: RuleLabel, saved: dict[str, object], keys: dict[str, list[str]]) -> dict[str, object]:
    if label.fields[0] in keys:
        field = label.fields[0]
        return {field: per_key(label, keys[field], saved[field])}
    if label.fields == ("budget_mode",):
        mode = st.radio(
            sentence(label, saved, blank="budget_mode"),
            list(BudgetMode),
            index=list(BudgetMode).index(saved["budget_mode"]),
            format_func=lambda m: f"{BUDGET_MODE_NAMES[m].capitalize()} cost",
            horizontal=True,
            key=f"{PREFIX}budget_mode",
        )
        return {"budget_mode": mode}
    out = {}
    for column, field in zip(st.columns(len(label.fields)), label.fields, strict=True):
        with column:
            out[field] = number(field, sentence(label, saved, blank=field), saved[field], label.help)
    return out


def changes_table(changes: list[Change], name: str) -> None:
    if not changes:
        st.caption(f"No change by {name}.")
        return
    st.dataframe(
        [{name: c.name, "now": c.current, "with your edits": c.new, "change": c.change} for c in changes],
        hide_index=True,
    )


def show_preview(result: PreviewResult) -> None:
    st.markdown(f"**{result.headline()}**")
    st.caption(
        f"One Daily Sweep at {result.at.strftime(data.TIME_FORMAT)}, decided by the rules chooser, under the "
        f"current Rules and under your edits. {len(result.newly_blocked):,} Customers lose their Offer and "
        f"{len(result.newly_unblocked):,} get one. Nothing is saved until **Save**."
    )
    type_col, binding_col = st.columns(2)
    with type_col:
        changes_table(result.type_changes(), "Offer Type")
    with binding_col:
        changes_table(result.binding_changes(), "Binding Rule")


st.title("Rules")
st.caption(
    "Every Offer must satisfy these. A change applies to new Decisions only; Offers already made keep the rule "
    "version they passed."
)
if flash := st.session_state.pop("rules_flash", None):
    st.success(flash)

conn = data.open_db()
try:
    version, rules = rules_store.current_rules(conn)
    if st.session_state.get("rules_version") != version:
        reset_form()
        st.session_state.rules_version = version
    saved = rules.to_dict()
    keys = {
        "max_pct_by_category": sorted(set(data.categories(conn)) | set(rules.max_pct_by_category)),
        "max_pct_by_loyalty_tier": [
            *LOYALTY_TIERS,
            *sorted(set(rules.max_pct_by_loyalty_tier) - set(LOYALTY_TIERS)),
        ],
    }

    st.markdown(f"Current version: **v{version}**")
    name_col, note_col = st.columns([1, 2])
    author = name_col.text_input("Your name", key="author").strip()
    note = note_col.text_input("Note", key="note", placeholder="Why this change?").strip()

    values: dict[str, object] = {}
    for group in GROUPS:
        with st.container(border=True):
            st.subheader(group)
            for label in (label for label in LABELS if label.group == group):
                values.update(rule_inputs(label, saved, keys))
                if label.fields == ("budget_mode",) and values["budget_mode"] == BudgetMode.EXPECTED:
                    st.warning(EXPECTED_WARNING)
                    exposure = data.worst_case_exposure(conn, rules)
                    st.caption(
                        f"Worst-case exposure this week: ₹{exposure:,.0f} of the ₹{values['weekly_budget']:,.0f} "
                        "budget."
                    )
                if label.fields == ("holdout_pct",) and values["holdout_pct"] != rules.holdout_pct:
                    st.warning(HOLDOUT_WARNING)

    new_rules = RuleSet.from_dict({f.name: values[f.name] for f in fields(RuleSet)})
    if st.button("Save", type="primary", key="save"):
        if not author or not note:
            st.error("Type your name and a note to save.")
        elif new_rules.send_hour_start >= new_rules.send_hour_end:
            st.error("The send hours must start before they end.")
        elif new_rules == rules:
            st.info("Nothing changed.")
        else:
            saved_version = rules_store.save_rules(conn, new_rules, author, note)
            finish(f"Saved v{saved_version}.")
    if st.button("Preview impact", key="preview"):
        if new_rules.send_hour_start >= new_rules.send_hour_end:
            st.error("The send hours must start before they end.")
        elif new_rules == rules:
            st.info("Nothing changed. Edit a Rule above to preview its impact.")
        else:
            with st.spinner("Running the next Daily Sweep with the current Rules and with your edits…"):
                show_preview(preview(conn, new_rules))

    st.header("Version history")
    history = data.rule_history(conn)
    st.dataframe(history, hide_index=True, key="history")
    for row in history.itertuples():
        if row.version == version:
            continue
        if st.button(f"Revert to this version (v{row.version})", key=f"revert.{row.version}"):
            if not author:
                st.error("Type your name to revert.")
            else:
                finish(f"Reverted to v{row.version} as v{rules_store.revert(conn, row.version, author)}.")

    st.header("Emergency withdraw")
    now = clock.now(conn)
    st.markdown(
        f"**{count_outstanding(conn, now):,}** outstanding Offers (queued, sent or claimed). Withdrawing makes "
        "their codes stop working, and each Customer with a chat who has seen theirs is told."
    )
    confirmed = st.checkbox("I understand this withdraws every outstanding Offer.", key="withdraw_confirm")
    if st.button("Withdraw outstanding Offers", disabled=not confirmed, key="withdraw"):
        if not author:
            st.error("Type your name to withdraw.")
        else:
            withdrawn = withdraw_outstanding(conn, now, author)
            del st.session_state["withdraw_confirm"]
            finish(f"Withdrew {withdrawn:,} Offers.")
    if past := list_withdrawals(conn):
        st.dataframe(
            [
                {"who": w.author, "when": w.created_at.strftime(data.TIME_FORMAT), "offers": w.offers}
                for w in past
            ],
            hide_index=True,
            key="withdrawals",
        )
finally:
    conn.close()
