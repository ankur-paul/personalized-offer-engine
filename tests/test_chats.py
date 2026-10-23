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


def save_cards(directory, *customer_ids, frozen=True):
    from offer_engine import personas

    for customer_id, case in zip(customer_ids, personas.CASES):
        personas.save(
            personas.PersonaCard(customer_id, case, f"Name {customer_id}", "A card.", frozen, "", 7, 50),
            directory,
        )


def test_link_showcase_links_frozen_cards_to_bots_in_order(env, conn, add_offer, tmp_path, capsys):
    for customer_id in ("C00001", "C00002", "C00003"):
        add_offer(code=f"POE-{customer_id[1:]}A", customer_id=customer_id, chat_id=None)
    save_cards(tmp_path / "personas", "C00002", "C00001")  # cases at_risk_high_value, new_one_order
    save_cards(tmp_path / "personas", "C00003", frozen=False)
    assert main(["chats", "link-showcase"]) == 0
    out = capsys.readouterr().out
    assert "C00002  at_risk_high_value" in out and "@poe_c1_bot" in out
    assert [
        tuple(r) for r in conn.execute("SELECT customer_id, chat_id, kind FROM chats ORDER BY chat_id")
    ] == [
        ("C00002", 111, "bot"),
        ("C00001", 222, "bot"),
    ]


def test_link_showcase_skips_optional_cases_when_bots_run_short(env, conn, add_offer, tmp_path, capsys):
    from offer_engine import personas

    add_offer(code="POE-00001A", customer_id="C00001", chat_id=None)
    add_offer(code="POE-00002A", customer_id="C00002", chat_id=None)
    save_cards(tmp_path / "personas", "C00001", "C00002")
    card = personas.PersonaCard("C00003", "persuadable", "Name", "A card.", True, "", 7, 50)
    personas.save(card, tmp_path / "personas")
    assert main(["chats", "link-showcase"]) == 0
    assert "skipped C00003 (persuadable, optional)" in capsys.readouterr().out
    assert conn.execute("SELECT COUNT(*) FROM chats").fetchone()[0] == 2


def test_link_showcase_needs_a_bot_per_required_card(env, conn, add_offer, tmp_path):
    save_cards(tmp_path / "personas", "C00001", "C00002", "C00003")
    with pytest.raises(SystemExit, match="3 required Persona Cards but 2 Customer Bots"):
        main(["chats", "link-showcase"])


def test_link_showcase_needs_frozen_cards(env):
    with pytest.raises(SystemExit, match="no frozen Persona Cards"):
        main(["chats", "link-showcase"])
