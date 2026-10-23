"""Calibration check (T15): each metric on a small hand-built history, and the pass/fail logic at range edges."""

from datetime import datetime, timedelta

import pytest

from offer_engine.cli import main
from offer_engine.sim import calibration
from offer_engine.sim.calibration import Metric, Window, measure

START = datetime(2025, 12, 1)
END = datetime(2026, 12, 1)
WINDOW = Window(START, END)


def day(n: int, hour: int = 12) -> datetime:
    return START + timedelta(days=n, hours=hour)


def customer(conn, cid: str, signup_at: datetime = START - timedelta(days=30)) -> None:
    conn.execute(
        "INSERT INTO customers (id, signup_at, city_tier, device, channel, loyalty_tier) VALUES (?, ?, 1, 'android',"
        " 'organic', 'bronze')",
        (cid, signup_at.isoformat()),
    )


def event(conn, cid: str, at: datetime, kind: str, category: str | None = None, amount=None, offer_id=None):
    conn.execute(
        "INSERT INTO events (customer_id, at, kind, category, amount, offer_id) VALUES (?, ?, ?, ?, ?, ?)",
        (cid, at.isoformat(), kind, category, amount, offer_id),
    )


def by_name(metrics: list[Metric], fragment: str) -> Metric:
    return next(m for m in metrics if fragment in m.name)


# --- Pass/fail -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("value", "passed"), [(0.70, True), (0.80, True), (0.6999, False), (0.8001, False)])
def test_a_metric_passes_inside_its_range_edges_included(value, passed):
    assert Metric("2", "Cart abandonment", value, 0.70, 0.80).passed is passed


def test_an_empty_history_measures_nothing(conn):
    assert measure(conn, END) == []


def test_events_at_or_after_the_end_are_ignored(conn):
    customer(conn, "C1")
    for n in range(10):
        event(conn, "C1", day(n), "add_to_cart", "grocery")
    for n in range(7):
        event(conn, "C1", day(n, 13), "cart_abandoned", "grocery")
    event(conn, "C1", END, "add_to_cart", "grocery")
    event(conn, "C1", END + timedelta(days=1), "add_to_cart", "grocery")
    assert by_name(measure(conn, END), "Cart abandonment").value == pytest.approx(0.7)


# --- 1, 1a, 2: the organic funnel ---------------------------------------------------------------------------


def test_conversion_overall_and_the_category_order(conn):
    customer(conn, "C1")
    for category, sessions, orders in (
        ("grocery", 100, 3),
        ("beauty", 100, 2),
        ("home", 100, 1),
        ("electronics", 100, 0),
    ):
        for n in range(sessions):
            event(conn, "C1", day(n % 300), "session", category)
        for n in range(orders):
            event(conn, "C1", day(n), "order", category, 500.0)
    overall, gap = calibration.conversion(conn, WINDOW)
    assert overall.value == pytest.approx(6 / 400)
    assert overall.passed and not overall.split
    assert gap.value == pytest.approx(0.02 - 0.01)  # min(grocery, beauty) − max(home, electronics)
    assert gap.split


def test_weekly_base_over_customers_active_at_the_end(conn):
    bases = [0.01] * 5 + [0.02] * 4 + [0.50]
    for i, base in enumerate(bases):
        customer(conn, f"C{i}")
        conn.execute(
            "INSERT INTO sim_customer_traits VALUES (?, 1, 1, 1, '{}', 0.5, 0.001, NULL)", (f"C{i}",)
        )
        conn.execute("INSERT INTO sim_ground_truth VALUES (?, 'nudge', ?, 0.01, 0.5)", (f"C{i}", base))
    customer(conn, "LAPSED")
    conn.execute(
        "INSERT INTO sim_customer_traits VALUES ('LAPSED', 1, 1, 1, '{}', 0.5, 0.001, '2026-05-01T00:00:00')"
    )
    conn.execute("INSERT INTO sim_ground_truth VALUES ('LAPSED', 'nudge', 0.9, 0.01, 0.5)")
    mean, median, top = calibration.weekly_base(conn, WINDOW)
    assert mean.value == pytest.approx(sum(bases) / 10)
    assert median.value == pytest.approx(0.015)
    assert top.value == pytest.approx(0.50)  # the top decile of 10 is one Customer


# --- 3, 3a, 4, 12: past Offers ---------------------------------------------------------------------------


def past_offer(conn, offer_id: int, trigger: str, status: str, p: float, cid: str = "C1") -> None:
    conn.execute(
        "INSERT INTO offers (id, code, customer_id, offer_type, created_at, send_at, expires_at, rule_version,"
        " worst_case_cost, expected_cost, status, source) VALUES (?, ?, ?, 'nudge', ?, ?, ?, 0, 0, 0, ?,"
        " 'history_random')",
        (
            offer_id,
            f"POE-{offer_id:06d}",
            cid,
            day(1).isoformat(),
            day(1).isoformat(),
            day(4).isoformat(),
            status,
        ),
    )
    conn.execute(
        "INSERT INTO sim_history_moments (customer_id, at, trigger, offer_id, p_buy) VALUES (?, ?, ?, ?, ?)",
        (cid, day(1).isoformat(), trigger, offer_id, p),
    )


def unsent_moment(conn, trigger: str, p: float, cid: str = "C1") -> None:
    conn.execute(
        "INSERT INTO sim_history_moments (customer_id, at, trigger, offer_id, p_buy) VALUES (?, ?, ?, NULL, ?)",
        (cid, day(1).isoformat(), trigger, p),
    )


def test_cart_recovery_and_the_share_that_would_have_bought_anyway(conn):
    customer(conn, "C1")
    for i in range(10):
        past_offer(conn, i + 1, "cart_abandoned", "redeemed" if i == 0 else "expired", 0.20)
    for _ in range(20):
        unsent_moment(conn, "cart_abandoned", 0.12)
    recovery, anyway = calibration.cart_recovery(conn)
    assert recovery.value == pytest.approx(0.1)
    assert anyway.value == pytest.approx(0.6)


def test_redemption_per_send_targeted_and_broadcast(conn):
    customer(conn, "C1")
    past_offer(conn, 1, "cart_abandoned", "redeemed", 0.2)
    past_offer(conn, 2, "long_gap", "expired", 0.2)
    past_offer(conn, 3, "long_gap", "claimed", 0.2)
    past_offer(conn, 4, "long_gap", "expired", 0.2)
    for i in range(5, 105):
        past_offer(conn, i, "broadcast", "redeemed" if i == 5 else "expired", 0.01)
    unsent_moment(conn, "broadcast", 0.9)  # moments without an Offer don't count
    targeted, broadcast = calibration.redemption_per_send(conn)
    assert targeted.value == pytest.approx(0.25)
    assert broadcast.value == pytest.approx(0.01)
    assert broadcast.passed  # the upper edge


def test_opt_out_per_past_offer_sent(conn):
    customer(conn, "C1")
    for i in range(1, 201):
        past_offer(conn, i, "broadcast", "dismissed" if i == 1 else "expired", 0.01)
    event(conn, "C1", day(2), "opted_out", offer_id=1)
    (metric,) = calibration.opt_outs(conn)
    assert metric.value == pytest.approx(0.005)
    assert metric.passed


def test_no_past_offers_means_no_offer_metrics(conn):
    assert calibration.cart_recovery(conn) == []
    assert calibration.redemption_per_send(conn) == []
    assert calibration.opt_outs(conn) == []


# --- 5, 5a, 6, 8, 10: orders -------------------------------------------------------------------------------


def orders_of(conn, cid: str, days: list[int], category: str = "grocery", amount: float = 100.0) -> None:
    for n in days:
        event(conn, cid, day(n), "order", category, amount)


def load_orders(conn):
    return calibration._orders(conn, WINDOW)


def test_repeat_90_days_among_new_customers_by_first_category(conn):
    customer(conn, "OLD")  # signed up before the history: not new
    orders_of(conn, "OLD", [10, 20])
    customer(conn, "N1", day(0))
    orders_of(conn, "N1", [5, 90])  # again within 90 days
    customer(conn, "N2", day(0))
    orders_of(conn, "N2", [5, 100])  # 95 days later: not a repeat
    customer(conn, "N3", day(0))
    orders_of(conn, "N3", [10], "fashion")
    customer(conn, "LATE", day(300))
    orders_of(conn, "LATE", [300, 301])  # first order under 90 days before the end: left out
    blended, *splits = calibration.repeat_90_days(conn, WINDOW, load_orders(conn))
    assert blended.value == pytest.approx(1 / 3)
    split = {m.name: m.value for m in splits}
    assert split["90-day repeat, first order in grocery"] == pytest.approx(0.5)
    assert split["90-day repeat, first order in fashion"] == 0.0
    assert all(m.split for m in splits)


def test_orders_per_year_blended_and_per_category_buyer(conn):
    for cid, n in (("C1", 2), ("C2", 6)):
        customer(conn, cid)
        orders_of(conn, cid, list(range(n)))
    orders_of(conn, "C1", [50], "fashion")
    blended, *splits = calibration.orders_per_year(WINDOW, load_orders(conn))
    assert blended.value == pytest.approx((3 + 6) / 2 * 365 / 365)
    split = {m.name: m.value for m in splits}
    assert split["Orders per grocery buyer per year"] == pytest.approx(4)
    assert split["Orders per fashion buyer per year"] == pytest.approx(1)


def test_lapse_uses_twice_the_category_median_gap(conn):
    # Grocery repeat buyers' own median gaps: 10, 10, 30 days → the category's is 10, so lapsed after 20 idle days.
    customer(conn, "A")
    orders_of(conn, "A", [1, 11, 21, 360])  # last order 5 days before the end: active
    customer(conn, "B")
    orders_of(conn, "B", [2, 12, 22, 300])  # idle 65 days: lapsed
    customer(conn, "C")
    orders_of(conn, "C", [200, 230])  # first order after the first 90 days: not in the cohort
    customer(conn, "D")
    orders_of(conn, "D", [3], "home")  # no home repeat buyers → 180-day cap; idle 362 days: lapsed
    customer(conn, "NEW", day(0))
    orders_of(conn, "NEW", [4])  # signed up in the history: left out
    lapsed = by_name(calibration.lapse(conn, WINDOW, load_orders(conn)), "Lapse")
    assert lapsed.value == pytest.approx(2 / 3)


def test_one_time_share_among_new_customers_of_the_first_half(conn):
    customer(conn, "N1", day(10))
    orders_of(conn, "N1", [10])
    customer(conn, "N2", day(10))
    orders_of(conn, "N2", [10, 200])
    customer(conn, "N3", day(20))  # never ordered: left out
    customer(conn, "LATE", day(250))  # second half: left out
    orders_of(conn, "LATE", [250])
    one_time = by_name(calibration.lapse(conn, WINDOW, load_orders(conn)), "one-time")
    assert one_time.value == pytest.approx(0.5)


def test_spend_concentration_of_the_top_buyers(conn):
    for i in range(100):
        customer(conn, f"C{i:03d}")
        orders_of(conn, f"C{i:03d}", [1], amount=1_900.0 if i == 0 else 100.0)
    top20, top10, top1 = calibration.spend_concentration(load_orders(conn))
    total = 1_900 + 99 * 100
    assert top1.value == pytest.approx(1_900 / total)
    assert top10.value == pytest.approx((1_900 + 9 * 100) / total)
    assert top20.value == pytest.approx((1_900 + 19 * 100) / total)


def test_festive_and_peak_week_shares_of_a_years_gmv(conn):
    customer(conn, "C1")
    event(conn, "C1", datetime(2026, 1, 10), "order", "grocery", 700.0)
    event(conn, "C1", datetime(2026, 9, 15, 9), "order", "grocery", 200.0)  # festive window's first day
    event(conn, "C1", datetime(2026, 11, 7, 21), "order", "grocery", 100.0)  # peak week's last day
    festive, peak = calibration.seasonality(WINDOW, load_orders(conn))
    assert festive.value == pytest.approx(0.3)
    assert peak.value == pytest.approx(0.1)


def test_seasonality_needs_a_full_year(conn):
    customer(conn, "C1")
    event(conn, "C1", datetime(2026, 11, 2), "order", "grocery", 100.0)
    assert calibration.seasonality(Window(datetime(2026, 9, 1), END), load_orders(conn)) == []


# --- 7, 9, 11: catalog, Ground Truth, points ------------------------------------------------------------


def test_margins_per_category(conn):
    conn.execute("INSERT INTO categories VALUES ('grocery', 12.0, 650), ('fashion', 51.0, 1400)")
    fashion, grocery = calibration.margins(conn)
    assert grocery.value == pytest.approx(0.12) and grocery.passed
    assert fashion.value == pytest.approx(0.51) and not fashion.passed


def test_response_class_shares_blanket_lift_and_sure_things_among_redeemers(conn):
    rows = [("S", "sure_thing", 0.20, 0.0), ("P", "persuadable", 0.02, 0.10), ("L", "lost_cause", 0.0, 0.0)]
    rows += [(f"L{i}", "lost_cause", 0.0, 0.0) for i in range(7)]
    for cid, cls, base, max_lift in rows:
        customer(conn, cid)
        conn.execute(
            "INSERT INTO sim_ground_truth VALUES (?, 'pct_category', ?, ?, 0.15)", (cid, base, max_lift)
        )
        conn.execute("INSERT INTO sim_response_class VALUES (?, ?)", (cid, cls))
    metrics = calibration.response_classes(conn)
    assert by_name(metrics, "lost cause").value == pytest.approx(0.8)
    assert by_name(metrics, "sure thing").value == pytest.approx(0.1)
    assert by_name(metrics, "sleeping dog").value == 0.0
    lift = 0.10 * (1 - 2.718281828**-1)  # 15% off with k = 0.15
    assert by_name(metrics, "relative Lift").value == pytest.approx(lift / 0.22, rel=1e-6)
    assert by_name(metrics, "redeemers").value == pytest.approx(0.20 / (0.22 + lift), rel=1e-6)


def test_points_breakage_and_earners_who_never_burn(conn):
    for cid in ("A", "B", "C", "BONUS_ONLY"):
        customer(conn, cid, day(0))
    customer(conn, "OLD")  # signed up before the history: its earlier burns aren't seen, so it's left out
    event(conn, "OLD", day(5), "points_earned", "grocery", 100.0)
    event(conn, "OLD", day(6), "points_expired", amount=500.0)
    event(conn, "A", day(5), "points_earned", "grocery", 300.0)
    event(conn, "A", day(9), "points_burned", "grocery", 300.0)
    event(conn, "B", day(5), "points_earned", "fashion", 100.0)
    event(conn, "B", day(190), "points_expired", amount=100.0)
    event(conn, "C", day(5), "points_earned", "home", 50.0)  # still unspent at the end: not in breakage
    event(
        conn, "BONUS_ONLY", day(1), "points_earned", amount=100.0
    )  # signup bonus: no category, not an earner
    breakage, never = calibration.points(conn, WINDOW)
    assert breakage.value == pytest.approx(100 / 400)
    assert never.value == pytest.approx(2 / 3)


# --- `offer-engine calibrate` -----------------------------------------------------------------------------


@pytest.fixture
def fake_metrics(monkeypatch, conn, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    found: list[Metric] = []
    monkeypatch.setattr(calibration, "measure", lambda conn: found)
    return found


def test_calibrate_prints_a_table_and_strict_fails_on_a_miss(fake_metrics, capsys):
    fake_metrics += [
        Metric("2", "Cart abandonment", 0.73, 0.70, 0.80),
        Metric("8", "Top 1% share", 0.23, 0.10, 0.20),
    ]
    assert main(["calibrate"]) == 0
    out = capsys.readouterr().out
    assert "Cart abandonment" in out and "73.0%" in out and "MISS" in out
    assert main(["calibrate", "--strict"]) == 1


def test_strict_ignores_category_splits(fake_metrics, capsys):
    fake_metrics += [
        Metric("2", "Cart abandonment", 0.73, 0.70, 0.80),
        Metric("5a", "Orders per grocery buyer per year", 6.6, 24, 40, calibration.COUNT, split=True),
    ]
    assert main(["calibrate", "--strict"]) == 0
    assert "miss (category split)" in capsys.readouterr().out
