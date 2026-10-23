"""The marketing console (PLAN §6): `streamlit run console/app.py`. Every page shows the simulated time in the
sidebar; a password gate guards them all when `CONSOLE_PASSWORD` is set."""

from __future__ import annotations

import hmac
import sys
from pathlib import Path

# `streamlit run` puts only this folder on sys.path; the pages import the `console` package from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from console import data
from offer_engine.config import load_settings

st.set_page_config(page_title="Offer Engine console", layout="wide")


def password_gate(password: str | None) -> None:
    """Stop the run until this session has typed `password`."""
    if not password or st.session_state.get("authenticated"):
        return
    typed = st.text_input("Console password", type="password", key="password")
    if typed and hmac.compare_digest(typed.encode(), password.encode()):
        st.session_state.authenticated = True
        st.rerun()
    if typed:
        st.error("Wrong password.")
    st.stop()


password_gate(load_settings().console_password)

conn = data.open_db()
if conn is None:
    st.error(
        "The database isn't initialised. Run `uv run offer-engine generate` (or `offer-engine db init`)."
    )
    st.stop()
st.sidebar.metric("Simulated time", data.sim_time(conn))
conn.close()

page = st.navigation(
    [
        st.Page("pages/1_clock.py", title="Simulation Clock", default=True),
        st.Page("pages/2_decisions.py", title="Decision log"),
        st.Page("pages/3_rules.py", title="Rules"),
    ]
)
page.run()
