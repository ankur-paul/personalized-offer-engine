"""Customer responses (T10, PLAN §4.1, §3.3): Claim, Not now, Stop and `/start` change the database and reply."""

from __future__ import annotations

import re
from datetime import datetime

import pytest

from offer_engine import clock
from offer_engine.customers import load_customer_state
from offer_engine.domain import RuleSet
from offer_engine.offer_bot import responses
from offer_engine.offer_bot.handlers.responses import (
    BUTTON_PATTERN,
    CODE_COMMAND_PATTERN,
    STOP_PATTERN,
    respond,
)
from offer_engine.rules import eligible_set, fatigue_paused_until

NOW = datetime(2026, 12, 1, 12, 0)
CODE = "POE-AB12CD"
CHAT = 4242


@pytest.fixture(autouse=True)
def at_noon(conn):
    clock.set_now(conn, NOW)


def status(conn, code=CODE) -> str:
    return conn.execute("SELECT status FROM offers WHERE code = ?", (code,)).fetchone()[0]


def events(conn, kind=None) -> list[tuple]:
    rows = conn.execute("SELECT customer_id, at, kind, category, offer_id FROM events ORDER BY id").fetchall()
    return [tuple(row) for row in rows if kind is None or row["kind"] == kind]


def opted_out(conn, customer_id="C00042") -> bool:
    return bool(conn.execute("SELECT opted_out FROM customers WHERE id = ?", (customer_id,)).fetchone()[0])


# --- Claim and Not now -------------------------------------------------------------------------


def test_claim_marks_the_offer_claimed_and_records_the_event(conn, add_offer):
    offer_id = add_offer()
    reply = responses.claim(conn, CODE, CHAT)
    assert reply == "Claimed! Your code is POE-AB12CD. It's valid until 4 Dec, 10:00."
    assert status(conn) == "claimed"
    assert events(conn) == [("C00042", "2026-12-01T12:00:00", "offer_claimed", "fashion", offer_id)]


def test_claim_again_repeats_the_reply_without_a_second_event(conn, add_offer):
    add_offer()
    first = responses.claim(conn, CODE, CHAT)
    assert responses.claim(conn, CODE.lower(), CHAT) == first
    assert len(events(conn)) == 1


def test_not_now_marks_the_offer_dismissed(conn, add_offer):
    offer_id = add_offer()
    assert responses.dismiss(conn, CODE, CHAT) == "No problem. We'll ease off for a bit."
    assert status(conn) == "dismissed"
    assert events(conn) == [("C00042", "2026-12-01T12:00:00", "offer_dismissed", "fashion", offer_id)]
    assert responses.dismiss(conn, CODE, CHAT) == responses.DISMISSED
    assert len(events(conn)) == 1


def test_not_now_after_a_claim_keeps_the_claim(conn, add_offer):
    add_offer()
    responses.claim(conn, CODE, CHAT)
    assert responses.dismiss(conn, CODE, CHAT) == f"You've already claimed {CODE}."
    assert status(conn) == "claimed"


def test_a_dismissed_offer_cant_be_claimed(conn, add_offer):
    add_offer()
    responses.dismiss(conn, CODE, CHAT)
    assert responses.claim(conn, CODE, CHAT) == responses.NOT_ACTIVE
    assert status(conn) == "dismissed"


def test_only_the_customers_chat_may_act_on_the_offer(conn, add_offer):
    add_offer()
    add_offer(code="POE-ZZ99ZZ", customer_id="C00007", chat_id=7777)
    assert responses.claim(conn, CODE, 7777) == "That code isn't yours."
    assert responses.dismiss(conn, CODE, 9999) == "That code isn't yours."
    assert status(conn) == "sent"
    assert events(conn) == []


def test_an_offer_without_a_chat_isnt_anyones(conn, add_offer):
    add_offer(chat_id=None)
    assert responses.claim(conn, CODE, CHAT) == responses.NOT_YOURS


def test_an_expired_code_isnt_active(conn, add_offer):
    add_offer(expires_at=NOW)
    assert responses.claim(conn, CODE, CHAT) == "That code isn't active any more."
    assert responses.dismiss(conn, CODE, CHAT) == responses.NOT_ACTIVE
    assert status(conn) == "sent"


@pytest.mark.parametrize("offer_status", ["queued", "withdrawn", "expired", "redeemed"])
def test_codes_that_arent_out_arent_active(conn, add_offer, offer_status):
    add_offer(status=offer_status)
    assert responses.claim(conn, CODE, CHAT) == responses.NOT_ACTIVE
    assert status(conn) == offer_status


def test_an_unknown_code_isnt_active(conn, add_offer):
    add_offer()
    assert responses.claim(conn, "POE-NOPE00", CHAT) == responses.NOT_ACTIVE


def test_three_not_nows_start_a_fatigue_pause(conn, add_offer):
    for i in range(3):
        add_offer(code=f"POE-FAT00{i}")
        responses.dismiss(conn, f"POE-FAT00{i}", CHAT)
    state = load_customer_state(conn, "C00042", NOW)
    assert fatigue_paused_until(state, RuleSet()) is not None
    assert eligible_set(state, RuleSet(), None, NOW, None).short_circuit == "fatigue_pause"


# --- Stop and /start ---------------------------------------------------------------------------


def test_stop_opts_out_and_withdraws_queued_offers(conn, add_offer):
    add_offer()
    add_offer(code="POE-QUEUE1", status="queued", send_at=datetime(2026, 12, 1, 14, 0))
    reply = responses.stop(conn, CHAT)
    assert reply == "You won't get any more offers. Send /start any time to turn them back on."
    assert opted_out(conn)
    assert status(conn, "POE-QUEUE1") == "withdrawn"
    assert status(conn) == "sent"
    assert events(conn) == [("C00042", "2026-12-01T12:00:00", "opted_out", None, None)]


def test_stop_twice_records_one_opt_out(conn, add_offer):
    add_offer()
    responses.stop(conn, CHAT)
    assert responses.stop(conn, CHAT) == responses.STOPPED
    assert len(events(conn, "opted_out")) == 1


def test_an_opted_out_customer_gets_no_eligible_set(conn, add_offer):
    add_offer()
    responses.stop(conn, CHAT)
    state = load_customer_state(conn, "C00042", NOW)
    assert eligible_set(state, RuleSet(), None, NOW, None).short_circuit == "opt_out"


def test_restart_opts_back_in(conn, add_offer):
    add_offer()
    responses.stop(conn, CHAT)
    assert responses.restart(conn, CHAT) == "Welcome back! You'll get offers again."
    assert not opted_out(conn)
    assert [e[2] for e in events(conn)] == ["opted_out", "opted_in"]
    assert responses.restart(conn, CHAT) == responses.ALREADY_ON
    assert len(events(conn)) == 2


def test_stop_and_restart_from_an_unlinked_chat(conn):
    assert responses.stop(conn, CHAT) == "This chat isn't linked to a Customer."
    assert responses.restart(conn, CHAT) == responses.NOT_LINKED


# --- Text commands and buttons -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "action", "code"),
    [
        (f"/claim {CODE}", "claim", CODE),
        ("/claim poe-ab12cd", "claim", "poe-ab12cd"),
        (f"/claim@poe_offer_bot {CODE}", "claim", CODE),
        (f"/NotNow {CODE}", "NotNow", CODE),
        ("/claim", "claim", None),
    ],
)
def test_code_command_pattern(text, action, code):
    match = re.match(CODE_COMMAND_PATTERN, text)
    assert match and match.groups() == (action, code)


@pytest.mark.parametrize(
    ("text", "action"),
    [
        ("Arre wah, taking this!\n/claim POE-AB12CD", "claim"),
        ("Maybe later.\n/notnow POE-AB12CD\n", "notnow"),
    ],
)
def test_code_command_may_follow_a_customer_bots_reply(text, action):
    match = re.search(CODE_COMMAND_PATTERN, text)
    assert match and match.groups() == (action, CODE)


@pytest.mark.parametrize("text", ["claim POE-AB12CD", "/claimed POE-AB12CD", "/claim A B", "/not now X"])
def test_code_command_pattern_rejects(text):
    assert re.match(CODE_COMMAND_PATTERN, text) is None


@pytest.mark.parametrize(
    ("text", "ok"), [("/stop", True), ("/STOP@poe_offer_bot", True), ("/stop now", False)]
)
def test_stop_pattern(text, ok):
    assert bool(re.match(STOP_PATTERN, text)) is ok


@pytest.mark.parametrize(
    ("data", "groups"),
    [
        (f"claim:{CODE}", ("claim", CODE, None)),
        (f"notnow:{CODE}", ("notnow", CODE, None)),
        ("stop", (None,) * 2 + ("stop",)),
    ],
)
def test_button_pattern(data, groups):
    assert re.match(BUTTON_PATTERN, data).groups() == groups


def test_respond_runs_each_action_against_the_database(conn, add_offer, tmp_path):
    add_offer()
    db = tmp_path / "test.db"
    assert respond(db, "claim", None, CHAT).startswith("Send /claim followed by the code")
    assert respond(db, "notnow", CODE, CHAT) == responses.DISMISSED
    assert respond(db, "stop", None, CHAT) == responses.STOPPED
    assert status(conn) == "dismissed" and opted_out(conn)
