import re
from datetime import datetime, timedelta

import pytest

from offer_engine.offer_bot import app as offer_bot_app
from offer_engine.offer_bot.handlers.demo import (
    CLAIM_PATTERN,
    DEMO_CODE,
    DEMO_CUSTOMER_ID,
    claim_reply,
    demo_offer,
    link_tester,
)

NOW = datetime(2026, 12, 1, 9, 0)


def test_demo_offer_is_valid_three_days_from_now():
    offer = demo_offer(NOW)
    assert offer.expires_at == NOW + timedelta(days=3)
    assert offer.params == {"pct": 15.0, "cap": 300.0}
    assert offer.caption.splitlines()[-1] == f"Code: {DEMO_CODE}"


def test_link_tester_creates_the_customer_and_relinks(conn):
    link_tester(conn, 111, NOW)
    link_tester(conn, 222, NOW)
    assert conn.execute("SELECT COUNT(*) FROM customers WHERE id = ?", (DEMO_CUSTOMER_ID,)).fetchone()[0] == 1
    row = conn.execute(
        "SELECT chat_id, kind FROM chats WHERE customer_id = ?", (DEMO_CUSTOMER_ID,)
    ).fetchone()
    assert tuple(row) == (222, "tester")


@pytest.mark.parametrize(
    ("text", "code"),
    [
        (f"/claim {DEMO_CODE}", DEMO_CODE),
        ("/claim poe-demo01", "poe-demo01"),
        (f"/claim@poe_offer_bot {DEMO_CODE}", DEMO_CODE),
        ("/CLAIM", None),
    ],
)
def test_claim_pattern(text, code):
    match = re.match(CLAIM_PATTERN, text)
    assert match and match.group(1) == code


@pytest.mark.parametrize("text", ["claim POE-DEMO01", "/claimed POE-DEMO01", "/claim A B"])
def test_claim_pattern_rejects(text):
    assert re.match(CLAIM_PATTERN, text) is None


def test_claim_replies():
    assert claim_reply(DEMO_CODE) == "Claimed POE-DEMO01. Show this code at checkout."
    assert claim_reply("poe-demo01").startswith("Claimed POE-DEMO01")
    assert "No Offer" in claim_reply("POE-XXXXXX")
    assert "/claim" in claim_reply(None)


def test_handler_modules_all_register():
    for name in offer_bot_app.HANDLER_MODULES:
        assert callable(__import__(name, fromlist=["register"]).register)


def test_both_bots_build_their_handlers_offline():
    from offer_engine.config import Settings
    from offer_engine.customer_sim import app as customer_sim_app

    settings = Settings(
        offer_bot_token="123:fake",
        offer_bot_username="poe_offer_bot",
        customer_bots=[("poe_c1_bot", "456:fake")],
    )
    assert sum(len(group) for group in offer_bot_app.build_app(settings).handlers.values()) == 2
    assert sum(len(group) for group in customer_sim_app.build_app(settings).handlers.values()) == 2
