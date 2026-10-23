"""Offer delivery (T10, PLAN "Assumed › World and time"): which Offers are due, and one delivery run's sends."""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from telegram.error import Forbidden

from offer_engine import clock
from offer_engine.offer_bot import delivery

NOW = datetime(2026, 12, 1, 12, 0)


@pytest.fixture(autouse=True)
def at_noon(conn):
    clock.set_now(conn, NOW)


def due_codes(conn) -> list[str]:
    return [d.offer.code for d in delivery.due_offers(conn, NOW)]


def test_picks_queued_due_offers_to_chat_attached_customers(conn, add_offer):
    add_offer(code="POE-DUE001", status="queued", send_at=datetime(2026, 12, 1, 11, 0))
    add_offer(code="POE-DUE002", status="queued", send_at=NOW)
    [first, _] = delivery.due_offers(conn, NOW)
    assert first.chat_id == 4242 and first.offer.params == {"pct": 15.0, "cap": 300.0}
    assert due_codes(conn) == ["POE-DUE001", "POE-DUE002"]


def test_skips_offers_not_due_not_queued_or_without_a_chat(conn, add_offer):
    add_offer(code="POE-LATER1", status="queued", send_at=datetime(2026, 12, 1, 13, 0))
    add_offer(code="POE-SENT01", status="sent")
    add_offer(code="POE-WDRAWN", status="withdrawn")
    add_offer(code="POE-NOCHAT", customer_id="C00009", chat_id=None, status="queued")
    add_offer(code="POE-EXPIRD", status="queued", expires_at=NOW)
    assert due_codes(conn) == []


def test_skips_opted_out_customers(conn, add_offer):
    add_offer(status="queued")
    conn.execute("UPDATE customers SET opted_out = 1")
    assert due_codes(conn) == []


def test_card_caption_adds_the_code_after_a_blank_line(conn, add_offer):
    add_offer(status="queued")
    [d] = delivery.due_offers(conn, NOW)
    assert delivery.card_caption(d.offer) == "Your fashion picks are waiting.\n\nCode: POE-AB12CD"


def test_card_buttons():
    [row] = delivery.card_buttons("POE-AB12CD").inline_keyboard
    assert [(b.text, b.callback_data) for b in row] == [
        ("Claim", "claim:POE-AB12CD"),
        ("Not now", "notnow:POE-AB12CD"),
        ("Stop", "stop"),
    ]


class FakeBot:
    def __init__(self, refuse: set[int] = frozenset()):
        self.refuse = refuse
        self.photos: list[dict] = []
        self.messages: list[tuple[int, str]] = []

    async def send_photo(self, chat_id, photo, caption, reply_markup):
        if chat_id in self.refuse:
            raise Forbidden("bot was blocked by the user")
        assert photo.startswith(b"\x89PNG")
        self.photos.append({"chat_id": chat_id, "caption": caption})

    async def send_message(self, chat_id, text):
        if chat_id in self.refuse:
            raise Forbidden("bot was blocked by the user")
        self.messages.append((chat_id, text))


def run_delivery(bot: FakeBot, tmp_path) -> None:
    context = SimpleNamespace(
        bot=bot, bot_data={"settings": SimpleNamespace(db_path=tmp_path / "test.db", customer_bots=[])}
    )
    asyncio.run(delivery.deliver(context))


def test_delivery_sends_cards_and_marks_them_sent(conn, add_offer, tmp_path):
    add_offer(status="queued", send_at=datetime(2026, 12, 1, 9, 0))
    bot = FakeBot()
    run_delivery(bot, tmp_path)
    assert bot.photos == [{"chat_id": 4242, "caption": "Your fashion picks are waiting.\n\nCode: POE-AB12CD"}]
    row = conn.execute("SELECT status, sent_at FROM offers").fetchone()
    assert tuple(row) == ("sent", "2026-12-01T12:00:00")
    run_delivery(bot, tmp_path)
    assert len(bot.photos) == 1


def test_a_refused_send_stays_queued_for_the_next_run(conn, add_offer, tmp_path):
    add_offer(status="queued")
    add_offer(code="POE-OTHER1", customer_id="C00007", chat_id=7777, status="queued")
    bot = FakeBot(refuse={4242})
    run_delivery(bot, tmp_path)
    assert [p["chat_id"] for p in bot.photos] == [7777]
    statuses = dict(conn.execute("SELECT code, status FROM offers").fetchall())
    assert statuses == {"POE-AB12CD": "queued", "POE-OTHER1": "sent"}


def test_outbox_messages_are_sent_once_in_order(conn, tmp_path):
    delivery.queue_message(conn, 4242, "Simulated order: ₹1,240 basket, code used")
    delivery.queue_message(conn, 4242, "Second")
    delivery.queue_message(conn, 13, "Blocked")
    conn.commit()
    bot = FakeBot(refuse={13})
    run_delivery(bot, tmp_path)
    run_delivery(bot, tmp_path)
    assert bot.messages == [(4242, "Simulated order: ₹1,240 basket, code used"), (4242, "Second")]
    assert [m.text for m in delivery.unsent_messages(conn)] == ["Blocked"]
    row = conn.execute("SELECT created_at, sent_at FROM outbox WHERE id = 1").fetchone()
    assert tuple(row) == ("2026-12-01T12:00:00", "2026-12-01T12:00:00")


def test_offer_bot_registers_the_delivery_job(monkeypatch):
    from offer_engine.config import Settings
    from offer_engine.offer_bot.app import build_app

    app = build_app(Settings(offer_bot_token="123:abc"))
    [job] = app.job_queue.jobs()
    assert job.name == "delivery" and job.callback is delivery.deliver


def test_customer_bot_chats_are_addressed_by_username():
    from offer_engine.offer_bot.delivery import send_target

    bots = [("ap_customer1_bot", "111:aaa"), ("@ap_customer2_bot", "222:bbb")]
    assert send_target(222, bots) == "@ap_customer2_bot"
    assert send_target(4242, bots) == 4242
