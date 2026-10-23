"""Daily Sweep hook, called by the day-step every simulated hour. T20 fills it: at 10:00 simulated time, run the
decision pipeline for every Customer, chat-attached ones first. Until then it does nothing."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any


def on_hour(conn: sqlite3.Connection, now: datetime, report: Any) -> None:
    """`report` is the day-step's DayReport; add counts to `report.counts`."""
