"""Event Triggers hook, called by the day-step every simulated hour. T19 fills it: run the decision pipeline for
the Customers whose new events fire a Trigger. Until then it does nothing."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from offer_engine.domain import Event


def on_hour(conn: sqlite3.Connection, now: datetime, new_events: list[Event], report: Any) -> None:
    """`new_events` are the events inserted this hour, so Triggers needn't re-scan the table. `report` is the
    day-step's DayReport; add counts to `report.counts`."""
