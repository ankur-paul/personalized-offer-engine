"""Estimated Lift v1 per segment (T16, PLAN §3.4)."""

from __future__ import annotations

import itertools
import re
from datetime import datetime, timedelta

import pytest

from offer_engine import clock, pipeline
from offer_engine.choosers.priors import lift_at
from offer_engine.cli import main
from offer_engine.customers import load_customer_state
from offer_engine.domain import (
    Customer,
    CustomerState,
    EligibleOption,
    Event,
    OfferStatus,
    OfferType,
    PastOffer,
    RuleSet,
    TriggerKind,
)
from offer_engine.lift import segment_lift
from offer_engine.rules import in_holdout

NOW = clock.START + timedelta(hours=10)
# The hand-built history starts on Saturday 21 Nov, so no Friday broadcast slot's 7 days end inside it.
FIRST_ORDER = datetime(2026, 11, 21, 10, 0)
CART = datetime(2026, 11, 22, 10, 0)
BUY = datetime(2026, 11, 24, 12, 0)
SIGNUP = datetime(2026, 11, 1)


def customer_ids(holdout: bool = False):
    for n in itertools.count(1):
        cid = f"T{n:05d}"
        if in_holdout(cid, RuleSet().holdout_pct) == holdout:
            yield cid


class History:
    """Writes a hand-built history: Customers with an abandoned cart on 22 Nov, maybe a past Offer at it."""

    def __init__(self, conn):
        self.conn = conn
        self.ids = customer_ids()
        self.offers = itertools.count(1)
        conn.execute("INSERT INTO categories VALUES ('grocery', 15.0, 900.0)")

    def customer(self, tier: str, *, ordered: bool, cid: str | None = None) -> str:
        cid = cid or next(self.ids)
        self.conn.execute(
            "INSERT INTO customers (id, signup_at, city_tier, device, channel, loyalty_tier, points_balance)"
            " VALUES (?, ?, 1, 'android', 'organic', ?, 0)",
            (cid, SIGNUP.isoformat(), tier),
        )
        if ordered:
            self.event(cid, FIRST_ORDER, "order")
        return cid

    def event(self, cid: str, at: datetime, kind: str) -> None:
        self.conn.execute(
            "INSERT INTO events (customer_id, at, kind, category, amount) VALUES (?, ?, ?, 'grocery', 900)",
            (cid, at.isoformat(), kind),
        )

    def offer(
        self, cid: str, offer_type: OfferType, at: datetime, *, redeemed_at: datetime | None = None
    ) -> None:
        oid = next(self.offers)
        status = OfferStatus.REDEEMED if redeemed_at else OfferStatus.EXPIRED
        self.conn.execute(
            "INSERT INTO offers (id, code, customer_id, offer_type, params, created_at, send_at, expires_at,"
            " rule_version, worst_case_cost, expected_cost, status, source, redeemed_at)"
            " VALUES (?, ?, ?, ?, '{}', ?, ?, ?, 0, 0, 0, ?, 'history_random', ?)",
            (
                oid,
                f"POE-T{oid:05d}",
                cid,
                offer_type,
                at.isoformat(),
                at.isoformat(),
                (at + timedelta(days=3)).isoformat(),
                status,
                redeemed_at.isoformat() if redeemed_at else None,
            ),
        )

    def group(self, tier: str, *, ordered: bool, n: int, buyers: int, offer: OfferType | None) -> list[str]:
        """`n` Customers whose cart abandoned on 22 Nov; `buyers` of them buy on 24 Nov."""
        out = []
        for i in range(n):
            cid = self.customer(tier, ordered=ordered)
            self.event(cid, CART, "cart_abandoned")
            if offer is not None:
                self.offer(cid, offer, CART, redeemed_at=BUY if i < buyers else None)
            if i < buyers:
                self.event(cid, BUY, "order")
            out.append(cid)
        return out


@pytest.fixture
def history(conn):
    return History(conn)


def gold_recent(history: History) -> None:
    """Gold Customers who ordered the day before: 30% buy after a Nudge, 20% without one, a +10-point Lift."""
    history.group("gold", ordered=True, n=200, buyers=60, offer=OfferType.NUDGE)
    history.group("gold", ordered=True, n=400, buyers=80, offer=None)


def row(conn, offer_type: OfferType, segment=None):
    if segment is None:
        return conn.execute(
            "SELECT * FROM lift_estimates WHERE offer_type = ? AND loyalty_tier IS NULL", (offer_type,)
        ).fetchone()
    tier, recency, coupon_user = segment
    return conn.execute(
        "SELECT * FROM lift_estimates WHERE offer_type = ? AND loyalty_tier = ? AND recency = ? AND coupon_user = ?",
        (offer_type, tier, recency, int(coupon_user)),
    ).fetchone()


def state(tier: str, events=(), offers=()) -> CustomerState:
    customer = Customer("X1", SIGNUP, 1, "android", "organic", tier, 0, None)
    return CustomerState(customer, tuple(events), tuple(offers))


def option(offer_type: OfferType) -> EligibleOption:
    return EligibleOption(offer_type, None, {}, {}, 0.0)


# --- Segments ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("days_ago", "recency"),
    [(1, "<=30"), (30, "<=30"), (31, "31-90"), (90, "31-90"), (91, ">90"), (None, ">90")],
)
def test_recency_bucket_is_days_since_the_last_order(days_ago, recency):
    events = [] if days_ago is None else [Event("X1", NOW - timedelta(days=days_ago), "order")]
    events.append(Event("X1", NOW - timedelta(days=120), "order"))
    assert segment_lift.segment_of(state("silver", sorted(events, key=lambda e: e.at)), NOW) == (
        "silver",
        recency,
        False,
    )


def test_coupon_user_redeemed_at_least_two_past_offers():
    def past(n: int, redeemed: bool) -> PastOffer:
        at = NOW - timedelta(days=10 * n)
        status = OfferStatus.REDEEMED if redeemed else OfferStatus.EXPIRED
        return PastOffer(
            n, OfferType.NUDGE, None, status, at, at + timedelta(days=3), at if redeemed else None
        )

    one = state("gold", offers=[past(1, True), past(2, False)])
    two = state("gold", offers=[past(1, True), past(2, True)])
    assert segment_lift.segment_of(one, NOW)[2] is False
    assert segment_lift.segment_of(two, NOW)[2] is True


# --- Fitting -----------------------------------------------------------------------------------


def test_recovers_a_known_lift_for_one_segment(conn, history):
    gold_recent(history)
    assert segment_lift.fit(conn) > 0
    r = row(conn, OfferType.NUDGE, ("gold", "<=30", False))
    assert (r["past_offers"], r["moments"]) == (200, 400)
    assert r["observed_lift"] == pytest.approx(0.10, abs=0.02)
    assert not r["from_type_avg"]
    # Estimated Lift is max Lift: back at a Nudge's depth it is the Lift observed.
    assert lift_at(OfferType.NUDGE, 1.0, r["estimated_lift"]) == pytest.approx(0.10, abs=0.02)
    assert r["fitted_at"] == clock.START.isoformat(timespec="seconds")


def test_sparse_segment_falls_back_to_the_offer_type_average(conn, history):
    gold_recent(history)
    history.group("bronze", ordered=False, n=20, buyers=1, offer=OfferType.NUDGE)
    history.group("bronze", ordered=False, n=40, buyers=2, offer=None)
    segment_lift.fit(conn)
    sparse = row(conn, OfferType.NUDGE, ("bronze", ">90", False))
    average = row(conn, OfferType.NUDGE)
    assert sparse["past_offers"] == 20 and sparse["from_type_avg"]
    assert sparse["estimated_lift"] == average["estimated_lift"]
    assert (average["past_offers"], average["moments"]) == (220, 440)


def test_moments_inside_an_offer_after_opt_out_or_in_the_holdout_do_not_count(conn, history):
    gold_recent(history)
    treated = history.group("gold", ordered=True, n=1, buyers=0, offer=OfferType.NUDGE)[0]
    history.event(treated, CART + timedelta(days=3), "cart_abandoned")
    opted = history.customer("gold", ordered=True)
    history.event(opted, CART - timedelta(hours=1), "opted_out")
    history.event(opted, CART, "cart_abandoned")
    held = history.customer("gold", ordered=True, cid=next(customer_ids(holdout=True)))
    history.event(held, CART, "cart_abandoned")
    segment_lift.fit(conn)
    assert row(conn, OfferType.NUDGE, ("gold", "<=30", False))["moments"] == 400


def test_a_later_fit_replaces_the_estimates(conn, history):
    gold_recent(history)
    segment_lift.fit(conn)
    clock.set_now(conn, NOW)
    n = segment_lift.fit(conn)
    assert conn.execute("SELECT COUNT(*) FROM lift_estimates").fetchone()[0] == n
    assert {r[0] for r in conn.execute("SELECT fitted_at FROM lift_estimates")} == {NOW.isoformat()}


def test_no_history_writes_nothing(conn):
    assert segment_lift.fit(conn) == 0
    assert segment_lift.load(conn, NOW) is None


# --- Estimating --------------------------------------------------------------------------------


def test_estimate_uses_the_segment_then_the_type_average_then_none(conn, history):
    gold_recent(history)
    history.group("bronze", ordered=False, n=20, buyers=1, offer=OfferType.NUDGE)
    segment_lift.fit(conn)
    fitted = segment_lift.load(conn, NOW)
    recent_gold = state("gold", [Event("X1", NOW - timedelta(days=5), "order")])
    assert fitted.estimate(recent_gold, option(OfferType.NUDGE)) == pytest.approx(
        row(conn, OfferType.NUDGE, ("gold", "<=30", False))["estimated_lift"]
    )
    unseen = state("platinum")
    assert fitted.estimate(unseen, option(OfferType.NUDGE)) == pytest.approx(
        row(conn, OfferType.NUDGE)["estimated_lift"]
    )
    assert fitted.estimate(recent_gold, option(OfferType.PCT_CATEGORY)) is None


def test_default_lift_estimator_is_none_until_fitted(world):
    eligible = next(r[0] for r in world.execute("SELECT id FROM customers ORDER BY id"))
    state_now = load_customer_state(world, eligible, NOW)
    assert pipeline.default_lift_estimator(world, NOW)(state_now, option(OfferType.NUDGE)) is None
    segment_lift.fit(world)
    assert pipeline.default_lift_estimator(world, NOW)(state_now, option(OfferType.NUDGE)) is not None


def test_decisions_rank_options_by_estimated_lift_after_a_fit(world):
    segment_lift.fit(world)
    rows = world.execute(
        "SELECT DISTINCT customer_id FROM events WHERE kind = 'add_to_cart' ORDER BY customer_id"
    ).fetchall()
    decided = [pipeline.decide(world, r[0], TriggerKind.CART_ABANDONED, NOW) for r in rows]
    reasons = [d.reason for d in decided if d.reason.startswith("highest expected value")]
    assert reasons and all("(estimated)" in r for r in reasons)


def test_generate_wipes_old_estimates(world):
    from offer_engine.sim.generate import run

    segment_lift.fit(world)
    run(world, 5, months=2, seed=3)
    assert world.execute("SELECT COUNT(*) FROM lift_estimates").fetchone()[0] == 0


# --- CLI ---------------------------------------------------------------------------------------


@pytest.fixture
def world_env(world, clean_env, monkeypatch):
    monkeypatch.setenv("DB_PATH", world.execute("PRAGMA database_list").fetchone()[2])
    return world


def test_cli_fit_then_show(world_env, capsys):
    cid = world_env.execute("SELECT customer_id FROM offers ORDER BY id LIMIT 1").fetchone()[0]
    assert main(["lift", "show", cid]) == 0
    assert "No Estimated Lift yet" in capsys.readouterr().out

    assert main(["lift", "fit"]) == 0
    out = capsys.readouterr().out
    assert re.search(r"^Fitted Estimated Lift from [\d,]+ past Offers", out, re.MULTILINE)
    assert all(t in out for t in OfferType)

    assert main(["lift", "show", cid]) == 0
    out = capsys.readouterr().out
    assert re.search(rf"^{cid} at 2026-12-01 00:00: \w+ · .+ · .*coupon user$", out, re.MULTILINE)
    assert all(re.search(rf"^  {t}\s+-?\d+\.\d%", out, re.MULTILINE) for t in OfferType)


def test_cli_show_unknown_customer(world_env):
    with pytest.raises(SystemExit, match="no Customer NOPE"):
        main(["lift", "show", "NOPE"])
