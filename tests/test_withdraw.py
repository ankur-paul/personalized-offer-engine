from datetime import datetime

import pytest

from offer_engine.domain import OfferStatus
from offer_engine.withdraw import NOTICE, count_outstanding, list_withdrawals, withdraw_outstanding

NOW = datetime(2026, 12, 1, 12)


@pytest.fixture
def db(conn):
    conn.executemany(
        "INSERT INTO customers (id, signup_at, city_tier, device, channel, loyalty_tier) VALUES (?, ?, 1, 'android',"
        " 'organic', 'bronze')",
        [(f"C0000{i}", "2026-01-01T00:00:00") for i in range(1, 9)],
    )
    return conn


def add_offer(conn, code, customer_id, status, *, expires_at="2026-12-03T12:00:00", source="live"):
    conn.execute(
        "INSERT INTO offers (code, customer_id, offer_type, created_at, send_at, expires_at, rule_version,"
        " worst_case_cost, expected_cost, status, source) VALUES (?, ?, 'free_shipping', ?, ?, ?, 0, 40, 4, ?, ?)",
        (code, customer_id, "2026-12-01T10:00:00", "2026-12-01T10:00:00", expires_at, status, source),
    )


def statuses(conn):
    return dict(conn.execute("SELECT code, status FROM offers").fetchall())


def outbox(conn):
    return [tuple(row) for row in conn.execute("SELECT chat_id, text, created_at FROM outbox ORDER BY id")]


def test_outstanding_offers_are_withdrawn_and_the_rest_untouched(db):
    add_offer(db, "POE-QUEUE1", "C00001", OfferStatus.QUEUED)
    add_offer(db, "POE-SENT01", "C00002", OfferStatus.SENT)
    add_offer(db, "POE-CLAIM1", "C00003", OfferStatus.CLAIMED)
    add_offer(db, "POE-REDEEM", "C00004", OfferStatus.REDEEMED)
    add_offer(db, "POE-EXPIRD", "C00005", OfferStatus.EXPIRED, expires_at="2026-11-30T12:00:00")
    add_offer(db, "POE-DISMIS", "C00006", OfferStatus.DISMISSED)
    add_offer(db, "POE-PAST01", "C00007", OfferStatus.CLAIMED, source="past")
    add_offer(db, "POE-LATE01", "C00008", OfferStatus.SENT, expires_at="2026-12-01T11:00:00")

    assert count_outstanding(db, NOW) == 3
    assert withdraw_outstanding(db, NOW, "Asha") == 3
    assert count_outstanding(db, NOW) == 0
    assert statuses(db) == {
        "POE-QUEUE1": "withdrawn",
        "POE-SENT01": "withdrawn",
        "POE-CLAIM1": "withdrawn",
        "POE-REDEEM": "redeemed",
        "POE-EXPIRD": "expired",
        "POE-DISMIS": "dismissed",
        "POE-PAST01": "claimed",
        "POE-LATE01": "sent",  # past its expiry: the day-step marks it expired
    }


def test_notices_go_only_to_chats_that_saw_the_offer(db):
    db.executemany(
        "INSERT INTO chats (customer_id, chat_id, kind) VALUES (?, ?, ?)",
        [("C00001", 101, "tester"), ("C00002", 102, "bot"), ("C00003", 103, "tester")],
    )
    add_offer(db, "POE-TESTER", "C00001", OfferStatus.SENT)
    add_offer(db, "POE-BOT001", "C00002", OfferStatus.CLAIMED)
    add_offer(db, "POE-QUEUED", "C00003", OfferStatus.QUEUED)  # card not sent yet, so no notice
    add_offer(db, "POE-NOCHAT", "C00004", OfferStatus.SENT)

    assert withdraw_outstanding(db, NOW, "Asha") == 4
    assert outbox(db) == [
        (101, NOTICE.format(code="POE-TESTER"), "2026-12-01T12:00:00"),
        (102, NOTICE.format(code="POE-BOT001"), "2026-12-01T12:00:00"),
    ]
    assert (
        NOTICE.format(code="POE-TESTER") == "This offer has been withdrawn: POE-TESTER. Sorry for the change."
    )


def test_each_withdrawal_is_logged_with_who_and_when(db):
    assert list_withdrawals(db) == []
    add_offer(db, "POE-SENT01", "C00002", OfferStatus.SENT)
    withdraw_outstanding(db, NOW, "Asha")
    withdraw_outstanding(db, datetime(2026, 12, 2), "Ravi")

    latest, first = list_withdrawals(db)
    assert (first.author, first.created_at, first.offers) == ("Asha", NOW, 1)
    assert (latest.author, latest.created_at, latest.offers) == ("Ravi", datetime(2026, 12, 2), 0)
    assert latest.saved_at.tzinfo is not None
