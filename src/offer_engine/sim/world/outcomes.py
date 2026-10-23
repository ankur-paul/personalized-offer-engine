"""Offer outcomes hook, called by the day-step every simulated hour. T18 fills it: Claims, Redemptions and
expiry settled by Ground Truth. Until then it does nothing."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from offer_engine.sim.world.day_step import DayReport


def on_hour(conn: sqlite3.Connection, now: datetime, report: DayReport, rng: np.random.Generator) -> None:
    """Settle Offers up to `now` and add counts to `report.counts`."""
