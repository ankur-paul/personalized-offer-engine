"""The Decision log: newest first, with reason, chooser, Binding Rule, rule version and Validation result.
Select a row to see its Offer's caption and status, and why the Decision came out as it did."""

from __future__ import annotations

import streamlit as st

from console import data

ALL = "All"
TABLE_COLUMNS = [
    "time",
    "customer",
    "trigger",
    "offer",
    "chooser",
    "reason",
    "binding_rule",
    "rule_version",
    "validation",
    "failures",
]

st.title("Decision log")

customer_col, trigger_col, chooser_col, hide_col = st.columns(4)
customer = customer_col.text_input("Customer ID", key="customer").strip()
trigger = trigger_col.selectbox("Trigger", [ALL, *data.TRIGGERS], key="trigger")
chooser = chooser_col.selectbox("Chooser", [ALL, *data.CHOOSERS], key="chooser")
hide_no_offer = hide_col.toggle("Hide No Offer", value=True, key="hide_no_offer")

conn = data.open_db()
try:
    frame = data.decisions(
        conn,
        customer_id=customer or None,
        trigger=None if trigger == ALL else trigger,
        chooser=None if chooser == ALL else chooser,
        hide_no_offer=hide_no_offer,
    )
finally:
    conn.close()

if frame.empty:
    st.info("No Decisions match. Advance the Simulation Clock to run the Triggers.")
    st.stop()

shown = f"latest {data.DECISION_LIMIT}" if len(frame) == data.DECISION_LIMIT else f"{len(frame)}"
st.caption(f"{shown} Decisions, newest first. Select a row to see its Offer.")
selection = st.dataframe(
    frame,
    column_order=TABLE_COLUMNS,
    # The full reason is under the table for the selected row; capping it here keeps the Binding Rule in view.
    column_config={"reason": st.column_config.TextColumn(width="medium")},
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    key="decisions",
)

if selection.selection.rows:
    row = frame.iloc[selection.selection.rows[0]]
    st.subheader(f"Decision #{row['id']} · {row['customer']}")
    if row["code"]:
        st.markdown(f"**Offer {row['code']}** · {row['offer']} · status **{row['status']}**")
        st.info(row["caption"] or "(no caption)")
    else:
        st.markdown("**No Offer**")
    if row["reason"]:
        st.markdown(f"**Reason:** {row['reason']}")
    if row["failures"]:
        st.markdown("**Validation failures:**")
        st.markdown("\n".join(f"- {failure}" for failure in row["failures"]))
    if row["chooser"] == "fallback" and row["agent_output"]:
        st.markdown("**Agent's rejected proposal:**")
        st.code(row["agent_output"], language="json")
    conn = data.open_db()
    try:
        stages = data.decision_trace(conn, int(row["id"]))
    finally:
        conn.close()
    with st.expander("Why"):
        if stages is None:
            st.caption("No trace: this Decision was made before traces were kept.")
        else:
            st.markdown("\n".join(f"- **{title}:** {summary}" for title, summary in stages))
            st.caption(f"Full trace: `offer-engine decisions explain {row['id']}`")
