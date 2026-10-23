"""Simulation Clock controls (ADR 0003): +1 hour, +1 day, and auto mode moving one simulated day every N
wall-clock seconds. Shows what the last step did."""

from __future__ import annotations

import time

import streamlit as st

from console import data

st.title("Simulation Clock")
st.caption(
    "Every Rule, event and expiry runs on simulated time. Advancing runs the marketplace hour by hour."
)


def step(hours: int) -> None:
    conn = data.open_db()
    try:
        report = data.advance(conn, hours)
    finally:
        conn.close()
    if report is None:
        st.toast("A step is still running; the clock didn't move.")
        return
    st.session_state.last_report = report
    st.rerun()


hour_col, day_col, _ = st.columns([1, 1, 4])
if hour_col.button("+1 hour", key="hour", width="stretch"):
    step(1)
if day_col.button("+1 day", key="day", type="primary", width="stretch"):
    step(24)

auto = st.toggle("Auto mode", key="auto", help="Advance 1 simulated day every N wall-clock seconds.")
seconds = st.slider("Seconds per simulated day", 5, 60, 10, key="auto_seconds", disabled=not auto)

if auto:
    # A full rerun (after each step, or any widget change) calls the fragment straight away; only a timer run,
    # `seconds` after the last step, may advance.
    st.session_state.setdefault("auto_last", time.monotonic())

    @st.fragment(run_every=seconds)
    def auto_step() -> None:
        if time.monotonic() - st.session_state.auto_last < seconds - 0.5:
            return
        st.session_state.auto_last = time.monotonic()
        step(24)

    auto_step()
else:
    st.session_state.pop("auto_last", None)

report = st.session_state.get("last_report")
if report is not None:
    st.subheader("Last step")
    st.write(f"{report.start:{data.TIME_FORMAT}} → {report.end:{data.TIME_FORMAT}}")
    counts = data.counts_frame(report.counts)
    if counts.empty:
        st.info("Nothing happened.")
    else:
        st.dataframe(counts, hide_index=True)
