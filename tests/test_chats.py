"""`offer-engine chats link` and `chats list` (T10)."""

from __future__ import annotations

import pytest

from offer_engine.cli import main
from offer_engine.commands.chats import bot_chat_ids, link

BOTS = "poe_c1_bot:111:aaa,@POE_C2_bot:222:bbb"


def test_bot_chat_ids_come_from_the_token():
    assert bot_chat_ids([("poe_c1_bot", "111:aaa"), ("@POE_C2_bot", "222:bbb")]) == {
        "poe_c1_bot": 111,
        "poe_c2_bot": 222,
    }


def test_link_moves_a_chat_off_its_previous_customer(conn, add_offer):
    add_offer(customer_id="C00001", chat_id=111)
    add_offer(code="POE-OTHER1", customer_id="C00002", chat_id=None)
    assert link(conn, "C00002", 111, "bot") == ["C00001"]
    assert [tuple(r) for r in conn.execute("SELECT customer_id, chat_id, kind FROM chats")] == [
        ("C00002", 111, "bot")
    ]
    assert link(conn, "C00002", 111, "bot") == []


@pytest.fixture
def env(clean_env, monkeypatch, conn, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("CUSTOMER_BOTS", BOTS)


def test_chats_link_and_list(env, conn, add_offer, capsys):
    add_offer(customer_id="C00042", chat_id=None)
    assert main(["chats", "link", "C00042", "--bot", "@poe_c2_bot"]) == 0
    assert "linked C00042 to @poe_c2_bot (chat 222)" in capsys.readouterr().out
    conn.execute("UPDATE customers SET opted_out = 1")
    conn.commit()
    assert main(["chats", "list"]) == 0
    assert capsys.readouterr().out == "C00042  bot     @poe_c2_bot (opted out)\n"


def test_chats_link_refuses_unknown_bots_and_customers(env, conn):
    with pytest.raises(SystemExit, match="@nobody_bot isn't in CUSTOMER_BOTS"):
        main(["chats", "link", "C00042", "--bot", "nobody_bot"])
    with pytest.raises(SystemExit, match="no Customer C00042"):
        main(["chats", "link", "C00042", "--bot", "poe_c1_bot"])


def test_chats_list_when_empty(env, capsys):
    assert main(["chats", "list"]) == 0
    assert "no chat-attached Customers" in capsys.readouterr().out
