from pathlib import Path

from streamlit.testing.v1 import AppTest

from offer_engine import rules_store
from offer_engine.domain import BudgetMode, RuleSet

APP = str(Path(__file__).resolve().parents[2] / "console" / "app.py")
PAGE = "pages/3_rules.py"


def rules_page() -> AppTest:
    app = AppTest.from_file(APP, default_timeout=60)
    app.run()
    app.switch_page(PAGE).run()
    assert not app.exception, app.exception
    return app


def texts(elements):
    return [e.value for e in elements]


def test_every_group_and_the_current_version(decision_db, console_env):
    app = rules_page()
    assert app.title[0].value == "Rules"
    assert texts(app.subheader) == ["Discounts", "Frequency", "Budget", "Timing", "Fatigue", "Holdout"]
    assert "Current version: **v0**" in texts(app.markdown)
    labels = [n.label for n in app.number_input]
    assert "Never discount below __% margin" in labels
    assert "Send at most __ offers per 7 days" in labels
    assert "Pause offers for 14 days after __ 'Not now' taps within 14 days" in labels
    assert "Give gold Customers at most __% off" in labels


def test_saving_with_a_name_creates_a_version(decision_db, console_env):
    app = rules_page()
    app.text_input(key="author").input("Asha")
    app.text_input(key="note").input("protect margins")
    app.number_input(key="rule.margin_floor_pct").set_value(10.0)
    app.number_input(key="rule.max_pct_by_category.fashion").set_value(12.0)
    app.button(key="save").click().run()
    assert not app.exception, app.exception

    version, rules = rules_store.current_rules(decision_db)
    assert version == 1
    assert rules == RuleSet(margin_floor_pct=10.0, max_pct_by_category={"fashion": 12.0})
    saved = rules_store.list_versions(decision_db)[0]
    assert (saved.author, saved.note) == ("Asha", "protect margins")
    assert "Saved v1." in texts(app.success)
    history = app.dataframe[0].value
    assert history["version"].tolist() == [1, 0]
    assert history.iloc[0]["who"] == "Asha"
    assert history.iloc[0]["when"] == "2026-12-01 00:00"
    assert history.iloc[0]["changed"] == "max_pct_by_category, margin_floor_pct"
    assert app.number_input(key="rule.margin_floor_pct").value == 10.0


def test_saving_without_a_name_shows_an_error(decision_db, console_env):
    app = rules_page()
    app.text_input(key="note").input("protect margins")
    app.number_input(key="rule.margin_floor_pct").set_value(10.0)
    app.button(key="save").click().run()
    assert "Type your name and a note to save." in texts(app.error)
    assert rules_store.current_rules(decision_db)[0] == 0


def test_send_hours_must_start_before_they_end(decision_db, console_env):
    app = rules_page()
    app.text_input(key="author").input("Asha")
    app.text_input(key="note").input("late sends")
    app.number_input(key="rule.send_hour_start").set_value(21)
    app.button(key="save").click().run()
    assert "The send hours must start before they end." in texts(app.error)
    assert rules_store.current_rules(decision_db)[0] == 0


def test_revert_creates_a_new_version(decision_db, console_env):
    rules_store.save_rules(decision_db, RuleSet(margin_floor_pct=10.0), "Asha", "protect margins")
    app = rules_page()
    assert app.number_input(key="rule.margin_floor_pct").value == 10.0
    assert [b.key for b in app.button if b.key.startswith("revert.")] == ["revert.0"]
    app.button(key="revert.0").click().run()
    assert "Type your name to revert." in texts(app.error)

    app.text_input(key="author").input("Ravi")
    app.button(key="revert.0").click().run()
    assert rules_store.current_rules(decision_db) == (2, RuleSet())
    latest = rules_store.list_versions(decision_db)[0]
    assert (latest.author, latest.note) == ("Ravi", "revert to v0")
    assert app.number_input(key="rule.margin_floor_pct").value == 5.0
    assert app.dataframe[0].value["version"].tolist() == [2, 1, 0]


def test_expected_mode_shows_the_overspend_warning(decision_db, console_env):
    # decision_db's Offers are made later in the day; make them count against this week's budget now.
    decision_db.execute("UPDATE offers SET created_at = '2026-11-30T12:00:00' WHERE source = 'live'")
    decision_db.commit()
    app = rules_page()
    assert not app.warning
    app.radio(key="rule.budget_mode").set_value(BudgetMode.EXPECTED).run()
    assert texts(app.warning) == [
        "Expected-cost budgeting can overspend if more Offers are redeemed than predicted."
    ]
    # Three queued Offers at ₹170 worst case each (₹20 expected).
    assert "Worst-case exposure this week: ₹510 of the ₹50,000 budget." in texts(app.caption)


def test_changing_the_holdout_warns(decision_db, console_env):
    app = rules_page()
    app.number_input(key="rule.holdout_pct").set_value(20.0).run()
    assert "changes who is in the Holdout" in app.warning[0].value


def test_withdraw_needs_the_confirmation(decision_db, console_env):
    app = rules_page()
    assert "**3** outstanding Offers" in " ".join(texts(app.markdown))
    assert app.button(key="withdraw").disabled
    app.text_input(key="author").input("Asha")
    app.checkbox(key="withdraw_confirm").check().run()
    app.button(key="withdraw").click().run()
    assert not app.exception, app.exception

    assert "Withdrew 3 Offers." in texts(app.success)
    statuses = decision_db.execute("SELECT DISTINCT status FROM offers WHERE source = 'live'").fetchall()
    assert [s[0] for s in statuses] == ["withdrawn"]
    assert app.button(key="withdraw").disabled
    log = app.dataframe[1].value
    assert (log["who"].tolist(), log["offers"].tolist()) == (["Asha"], [3])
    assert "**0** outstanding Offers" in " ".join(texts(app.markdown))
