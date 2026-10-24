"""The Results page (T27) renders with and without a Policy comparison."""

import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[2] / "console" / "app.py")
PAGE = "pages/4_results.py"
HEADERS = ["Policies", "Live funnel vs Holdout", "Wasted on Sure Things", "Validation", "Lift by decile"]
DECILES = json.dumps(
    [
        {"decile": 1, "offers": 50, "estimated_lift": 0.01, "true_lift": 0.004},
        {"decile": 2, "offers": 50, "estimated_lift": 0.03, "true_lift": 0.02},
    ]
)


def results_page() -> AppTest:
    app = AppTest.from_file(APP, default_timeout=60)
    app.run()
    app.switch_page(PAGE).run()
    assert not app.exception, app.exception
    return app


# AppTest keeps no key on a dataframe without selection, so tables are found by position: the Policy table first,
# the failure codes last.


def charts(app):
    return app.get("vega_lite_chart")


def add_policy_rows(conn, run_at="2026-10-24T10:00:00+00:00"):
    rows = [
        ("no_offers", "population", 0, 0, 0, 0.0, 0.0, None, 0.0, "[]"),
        ("rules_only", "population", 900, 300, 120, 9000.0, 250000.0, 27.78, 1200.0, DECILES),
        ("no_offers", "sample", 0, 0, 0, 0.0, 0.0, None, 0.0, "[]"),
        ("blanket_20", "sample", 400, 200, 150, 30000.0, -2400.0, -0.08, 9000.0, "[]"),
        ("rules_only", "sample", 45, 15, 6, 450.0, 13000.0, 28.89, 60.0, DECILES),
        ("rules_plus_agent", "sample", 40, 14, 5, 400.0, 9000.0, 22.5, 40.0, DECILES),
    ]
    conn.executemany(
        "INSERT INTO sim_policy_results (run_at, start_at, days, seed, policy, scope, customers, offers_sent,"
        " claimed, redeemed, spend, incremental_margin, per_rupee, sure_thing_spend, validation_rejections,"
        " fallbacks, lift_deciles, runtime_seconds)"
        " VALUES (?, '2026-12-01T00:00:00', 28, 7, ?, ?, 500, ?, ?, ?, ?, ?, ?, ?, 3, 1, ?, 60)",
        [(run_at, *row) for row in rows],
    )
    conn.commit()


def send_and_redeem(conn):
    """Send the decision_db's live Offers; C00001's is Claimed and Redeemed for ₹80."""
    conn.execute("UPDATE offers SET status = 'sent', sent_at = send_at WHERE source = 'live'")
    offer_id, customer = conn.execute(
        "SELECT id, customer_id FROM offers WHERE source = 'live' AND customer_id = 'C00001'"
    ).fetchone()
    conn.execute("UPDATE offers SET status = 'redeemed' WHERE id = ?", (offer_id,))
    conn.executemany(
        "INSERT INTO events (customer_id, at, kind, amount, offer_id) VALUES (?, '2026-12-01T15:00:00', ?, ?, ?)",
        [
            (customer, "offer_claimed", None, offer_id),
            (customer, "order", 900.0, offer_id),
            (customer, "offer_redeemed", 80.0, offer_id),
        ],
    )
    conn.commit()


def test_results_page_without_a_policy_run(decision_db, console_env):
    app = results_page()
    assert app.title[0].value == "Results"
    assert [h.value for h in app.header] == HEADERS
    infos = [i.value for i in app.info]
    assert any("No Policy comparison yet" in i for i in infos)
    assert any("No live Offers sent yet" in i for i in infos)
    assert any("Lift by decile comes from the Policy comparison" in i for i in infos)
    assert not app.radio
    # The decision_db's Fallback failed Validation, so the Validation chart is the one chart.
    assert len(charts(app)) == 1
    # That failure has no `code:` prefix, so the whole text is its code.
    codes = app.dataframe[-1].value
    assert codes["Failure"].tolist() == ["pct 40 above max 15 (max_pct_by_loyalty_tier)"]


def test_results_page_with_a_policy_run_and_live_offers(decision_db, console_env):
    add_policy_rows(decision_db, run_at="2026-10-20T10:00:00+00:00")  # an older run, not shown
    decision_db.execute("UPDATE sim_policy_results SET policy = 'old_' || policy")
    add_policy_rows(decision_db)
    send_and_redeem(decision_db)

    app = results_page()
    assert [h.value for h in app.header] == HEADERS
    assert not app.info
    assert app.radio(key="scope").value == "sample"
    table = app.dataframe[0].value
    assert table["Policy"].tolist() == ["No Offers", "Blanket 20%", "Rules Only", "Rules + Agent"]
    assert table["Per ₹ spent"].tolist() == ["baseline", "-0.08", "+28.89", "+22.50"]
    assert any("uv run offer-engine simulate --days 28 --seed 7" in c.value for c in app.caption)
    # Policies, funnel, Sure Things, Validation, Lift by decile.
    assert len(charts(app)) == 5
    assert app.selectbox(key="decile_policy").options == ["Rules Only", "Rules + Agent"]
    live_spend = next(m for m in app.metric if m.label == "Live offer spend on Sure Things")
    assert live_spend.value.endswith("of ₹80)")

    app.radio(key="scope").set_value("population").run()
    assert not app.exception, app.exception
    assert app.dataframe[0].value["Policy"].tolist() == ["No Offers", "Rules Only"]
    assert app.selectbox(key="decile_policy").options == ["Rules Only"]


def test_holdout_metrics_count_orders_since_the_clock_start(decision_db, console_env):
    app = results_page()
    labels = [m.label for m in app.metric]
    assert "Orders per Customer, can get offers" in labels
    assert "Orders per Customer, Holdout (10%)" in labels


def test_validation_says_so_when_nothing_failed(decision_db, console_env):
    decision_db.execute("UPDATE decisions SET validation_failures = '[]', chooser = 'rules'")
    decision_db.commit()
    app = results_page()
    assert app.success[0].value == "All 4 live Decisions passed Validation, with no Fallback."
    assert not charts(app)
