from datetime import datetime
from pathlib import Path

from streamlit.testing.v1 import AppTest

from offer_engine import clock

APP = str(Path(__file__).resolve().parents[2] / "console" / "app.py")
TIMEOUT = 60


def run_page(page: str | None = None) -> AppTest:
    app = AppTest.from_file(APP, default_timeout=TIMEOUT)
    app.run()
    if page:
        app.switch_page(page).run()
    assert not app.exception, app.exception
    return app


def test_clock_page_loads_with_the_simulated_time(decision_db, console_env):
    app = run_page()
    assert app.title[0].value == "Simulation Clock"
    assert app.sidebar.metric[0].value == "2026-12-01 00:00"
    assert [b.label for b in app.button] == ["+1 hour", "+1 day"]


def test_plus_one_day_moves_the_clock_24_hours(decision_db, console_env):
    app = run_page()
    app.button(key="day").click().run()
    assert not app.exception, app.exception
    assert clock.now(decision_db) == datetime(2026, 12, 2)
    # AppTest keeps sidebar elements only on a session's first run, so a new session reads the time.
    assert run_page().sidebar.metric[0].value == "2026-12-02 00:00"
    assert "2026-12-01 00:00 → 2026-12-02 00:00" in [m.value for m in app.markdown]
    counts = app.dataframe[0].value
    assert "session" in counts["what"].tolist()


def test_plus_one_hour(decision_db, console_env):
    app = run_page()
    app.button(key="hour").click().run()
    assert clock.now(decision_db) == datetime(2026, 12, 1, 1)


def test_auto_mode_does_not_advance_on_a_plain_rerun(decision_db, console_env):
    app = run_page()
    app.toggle(key="auto").set_value(True).run()
    app.run()
    assert not app.exception, app.exception
    assert clock.now(decision_db) == datetime(2026, 12, 1)


def test_decision_log_lists_decisions_with_filters(decision_db, console_env):
    app = run_page("pages/2_decisions.py")
    assert app.title[0].value == "Decision log"
    table = app.dataframe[0].value
    assert table["customer"].tolist() == ["C00003", "C00002", "C00001"]
    app.toggle(key="hide_no_offer").set_value(False).run()
    assert len(app.dataframe[0].value) == 4
    app.selectbox(key="chooser").set_value("fallback").run()
    assert app.dataframe[0].value["customer"].tolist() == ["C00003"]
    app.text_input(key="customer").set_value("C00001").run()
    assert not app.dataframe
    assert "No Decisions match" in app.info[0].value


def test_uninitialised_database_says_how_to_fix_it(console_env):
    app = AppTest.from_file(APP, default_timeout=TIMEOUT)
    app.run()
    assert "isn't initialised" in app.error[0].value


def test_password_gate(decision_db, console_env, monkeypatch):
    monkeypatch.setenv("CONSOLE_PASSWORD", "s3cret")
    app = AppTest.from_file(APP, default_timeout=TIMEOUT)
    app.run()
    assert not app.title and not app.sidebar.metric
    app.text_input(key="password").input("wrong").run()
    assert app.error[0].value == "Wrong password."
    app.text_input(key="password").input("s3cret").run()
    assert app.title[0].value == "Simulation Clock"
