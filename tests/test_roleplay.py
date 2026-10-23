"""Customer Bots' bounded role-play (T24; ADR 0004)."""

import json
import math
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from offer_engine import clock, personas
from offer_engine.customer_sim import roleplay
from offer_engine.customer_sim.roleplay import NEUTRAL, flip, nudged_chance, rate_fit, react, react_to_card
from offer_engine.offer_bot import responses
from offer_engine.personas import PersonaCard
from offer_engine.sim.world import outcomes
from offer_engine.sim.world.day_step import DayReport

SENT = clock.START + timedelta(hours=10)
EXPIRES = SENT + timedelta(days=3)
BOT_CHAT = 111


# --- The nudge ---------------------------------------------------------------------------------


@given(
    p_base=st.floats(min_value=0, max_value=1),
    fit=st.floats(allow_nan=True, allow_infinity=True),
)
def test_the_nudge_never_moves_the_chance_more_than_30_percent(p_base, fit):
    p = nudged_chance(p_base, fit)
    assert 0 <= p <= 1
    assert abs(p - p_base) <= 0.3 * p_base + 1e-12


def test_the_nudge_is_relative_and_clipped():
    assert nudged_chance(0.5, 1) == pytest.approx(0.65)
    assert nudged_chance(0.5, -1) == pytest.approx(0.35)
    assert nudged_chance(0.5, 40) == pytest.approx(0.65)
    assert nudged_chance(0.9, 1) == 1.0
    assert nudged_chance(0.5, math.nan) == 0.5
    assert nudged_chance(0.0, 1) == 0.0


@pytest.mark.parametrize("p_used", [0.05, 0.4, 0.9])
def test_seeded_flips_over_10000_runs_match_the_chance(p_used):
    rng = np.random.default_rng(3)
    draws = [flip(p_used, rng) for _ in range(10_000)]
    assert abs(sum(buys for buys, _ in draws) / 10_000 - p_used) < 0.01
    assert all(claims for buys, claims in draws if buys)
    non_buyers = [claims for buys, claims in draws if not buys]
    assert abs(sum(non_buyers) / len(non_buyers) - 0.25) < 0.03


# --- The agent ---------------------------------------------------------------------------------


class FakeClient:
    def __init__(self, tool_input=None, error=None, stop_reason="tool_use"):
        self.tool_input, self.error, self.stop_reason = tool_input, error, stop_reason
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        block = SimpleNamespace(type="tool_use", name=roleplay.TOOL_NAME, input=self.tool_input)
        return SimpleNamespace(stop_reason=self.stop_reason, content=[block])


def agent(fit=0.5, claim="Arre wah, taking this!", not_now="Maybe later, yaar."):
    return FakeClient({"fit": fit, "reply_claim": claim, "reply_not_now": not_now})


def test_rate_fit_sends_the_persona_caption_and_terms():
    client = agent()
    fit, replies = rate_fit(client, "fast-model", "Meera shops for kurtas.", "Your picks await.", ["20% off"])
    assert (fit, replies.claim, replies.not_now) == (0.5, "Arre wah, taking this!", "Maybe later, yaar.")
    prompt = client.calls[0]["messages"][0]["content"]
    assert "Meera shops for kurtas." in prompt and "Your picks await." in prompt and "- 20% off" in prompt
    assert client.calls[0]["model"] == "fast-model"


def test_replies_lose_commands_and_codes():
    _, replies = rate_fit(agent(claim="Sure /claim POE-AB12CD now", not_now="/stop"), "m", "card", "c", [])
    assert replies.claim == "Sure now"
    assert replies.not_now == NEUTRAL.not_now


@pytest.mark.parametrize(
    "client",
    [
        FakeClient(stop_reason="refusal", tool_input={}),
        FakeClient(stop_reason="max_tokens", tool_input={}),
        FakeClient({"fit": "very", "reply_claim": "a", "reply_not_now": "b"}),
    ],
)
def test_unusable_answers_raise(client):
    with pytest.raises(roleplay.RoleplayError):
        rate_fit(client, "m", "card", "c", [])


# --- Reacting to an Offer ----------------------------------------------------------------------


def persona(customer_id):
    return PersonaCard(customer_id, "deal_hunter", "Meera Iyer", "Meera hunts deals.", True, "", 7, 50)


@pytest.fixture
def bot_offer(world):
    """A sent Offer to the first Customer, linked to a Customer Bot. Returns a function giving its row."""
    customer_id = world.execute("SELECT id FROM customers ORDER BY id LIMIT 1").fetchone()[0]
    world.execute(
        "INSERT INTO chats (customer_id, chat_id, kind) VALUES (?, ?, 'bot')", (customer_id, BOT_CHAT)
    )
    cursor = world.execute(
        "INSERT INTO offers (code, customer_id, offer_type, category, params, created_at, send_at, sent_at, "
        "expires_at, caption, rule_version, worst_case_cost, expected_cost, status, source) "
        "VALUES ('POE-ROLE01', ?, 'pct_category', 'fashion', ?, ?, ?, ?, ?, 'Your fashion picks.', 0, 300, 60, "
        "'sent', 'live')",
        (
            customer_id,
            json.dumps({"pct": 20.0, "cap": 300.0}),
            *(t.isoformat() for t in (SENT, SENT, SENT, EXPIRES)),
        ),
    )
    clock.set_now(world, SENT)
    offer_id = cursor.lastrowid

    def row():
        return world.execute(
            "SELECT o.*, ch.kind AS chat_kind, ch.chat_id FROM offers o JOIN chats ch "
            "ON ch.customer_id = o.customer_id WHERE o.id = ?",
            (offer_id,),
        ).fetchone()

    return row


def make_buyer(conn, customer_id):
    conn.execute(
        "UPDATE sim_customer_traits SET visit_rate = 40, buy_propensity = 30, churned_at = NULL "
        "WHERE customer_id = ?",
        (customer_id,),
    )
    conn.commit()


def response_row(conn, offer_id):
    return conn.execute("SELECT * FROM sim_bot_responses WHERE offer_id = ?", (offer_id,)).fetchone()


def fate_row(conn, offer_id):
    return conn.execute("SELECT * FROM sim_offer_fates WHERE offer_id = ?", (offer_id,)).fetchone()


def test_the_agent_nudges_and_writes_the_reply(world, bot_offer):
    offer = bot_offer()
    client = agent(fit=1.0)
    reaction = react(world, offer, persona(offer["customer_id"]), client, "m", np.random.default_rng(0))
    row = response_row(world, offer["id"])
    assert row["fit"] == 1.0
    assert row["p_used"] == pytest.approx(min(1.0, row["p_base"] * 1.3))
    assert "Meera hunts deals." in client.calls[0]["messages"][0]["content"]
    expected = (
        "Arre wah, taking this!\n/claim POE-ROLE01"
        if reaction.claim
        else "Maybe later, yaar.\n/notnow POE-ROLE01"
    )
    assert reaction.reply_text == row["reply"] == expected
    assert (row["buys"], row["claims"]) == (reaction.buys, reaction.claim)


def test_a_huge_fit_still_nudges_by_at_most_30_percent(world, bot_offer):
    offer = bot_offer()
    react(world, offer, persona(offer["customer_id"]), agent(fit=1e9), "m", np.random.default_rng(0))
    row = response_row(world, offer["id"])
    assert row["p_used"] <= row["p_base"] * 1.3 + 1e-12


def test_an_agent_outage_falls_back_to_ground_truth_and_a_neutral_reply(world, bot_offer):
    offer = bot_offer()
    client = FakeClient(error=RuntimeError("overloaded"))
    reaction = react(world, offer, persona(offer["customer_id"]), client, "m", np.random.default_rng(0))
    row = response_row(world, offer["id"])
    assert row["fit"] == 0 and row["p_used"] == row["p_base"]
    assert reaction.reply_text.splitlines()[0] in (NEUTRAL.claim, NEUTRAL.not_now)


def test_no_persona_or_agent_means_a_plain_flip(world, bot_offer):
    offer = bot_offer()
    react(world, offer, None, None, None, np.random.default_rng(0))
    row = response_row(world, offer["id"])
    assert row["fit"] == 0 and row["p_used"] == row["p_base"]


def test_a_buyer_gets_a_roleplay_fate_and_redeems_through_t18(world, bot_offer):
    offer = bot_offer()
    make_buyer(world, offer["customer_id"])
    reaction = react(world, offer, None, None, None, np.random.default_rng(0))
    assert reaction.buys and reaction.claim
    fate = fate_row(world, offer["id"])
    assert fate["source"] == "bot_roleplay" and fate["buys"] == 1
    assert fate["claim_at"] is None and fate["dismiss_at"] is None
    buy_at = datetime.fromisoformat(fate["buy_at"])
    assert SENT <= buy_at < EXPIRES

    # The bot's /claim, as the Offer Bot applies it, then the clock passes the Redemption.
    assert responses.claim(world, offer["code"], BOT_CHAT).startswith("Claimed!")
    report = DayReport(SENT, EXPIRES)
    outcomes.on_hour(world, EXPIRES - timedelta(seconds=1), report, np.random.default_rng(1))
    assert world.execute("SELECT status FROM offers WHERE id = ?", (offer["id"],)).fetchone()[0] == "redeemed"
    assert report.counts["redeemed"] == 1 and report.counts["claimed"] == 0


def test_a_non_buyer_fate_has_no_redemption(world, bot_offer):
    offer = bot_offer()
    world.execute(
        "UPDATE sim_customer_traits SET visit_rate = 0, churned_at = NULL WHERE customer_id = ?",
        (offer["customer_id"],),
    )
    reaction = react(world, offer, None, None, None, np.random.default_rng(0))
    assert not reaction.buys
    assert fate_row(world, offer["id"])["buy_at"] is None
    assert reaction.reply_text.endswith(("/claim POE-ROLE01", "/notnow POE-ROLE01"))


def test_each_offer_gets_one_reaction(world, bot_offer):
    assert react(world, bot_offer(), None, None, None, np.random.default_rng(0)) is not None
    assert react(world, bot_offer(), None, None, None, np.random.default_rng(0)) is None
    world.execute("UPDATE offers SET status = 'claimed'")
    world.execute("DELETE FROM sim_bot_responses")
    world.execute("DELETE FROM sim_offer_fates")
    assert react(world, bot_offer(), None, None, None, np.random.default_rng(0)) is None


def test_react_to_card_only_for_this_bots_offers(world, bot_offer, tmp_path):
    offer = bot_offer()
    db_path = world.execute("PRAGMA database_list").fetchone()["file"]
    personas.save(persona(offer["customer_id"]), tmp_path)
    world.commit()
    assert react_to_card(db_path, "POE-ROLE01", 999, agent(), "m", 7, tmp_path) is None
    assert react_to_card(db_path, "POE-NOPE00", BOT_CHAT, agent(), "m", 7, tmp_path) is None
    client = agent()
    first = react_to_card(db_path, "poe-role01", BOT_CHAT, client, "m", 7, tmp_path)
    assert first is not None and "Meera hunts deals." in client.calls[0]["messages"][0]["content"]
    assert react_to_card(db_path, "POE-ROLE01", BOT_CHAT, client, "m", 7, tmp_path) is None


def test_a_card_that_arrives_before_the_offer_is_marked_sent_waits_for_it(world, bot_offer, monkeypatch):
    offer = bot_offer()
    db_path = world.execute("PRAGMA database_list").fetchone()["file"]
    world.execute("UPDATE offers SET status = 'queued' WHERE id = ?", (offer["id"],))
    world.commit()

    def mark_sent(seconds):  # the Offer Bot's mark_offer_sent lands while the Customer Bot waits
        world.execute("UPDATE offers SET status = 'sent' WHERE id = ?", (offer["id"],))
        world.commit()

    monkeypatch.setattr(roleplay.time, "sleep", mark_sent)
    assert react_to_card(db_path, "POE-ROLE01", BOT_CHAT, None, None, 7, wait_seconds=5) is not None


def test_a_card_whose_offer_stays_queued_gets_no_reaction(world, bot_offer):
    offer = bot_offer()
    db_path = world.execute("PRAGMA database_list").fetchone()["file"]
    world.execute("UPDATE offers SET status = 'queued' WHERE id = ?", (offer["id"],))
    world.commit()
    assert react_to_card(db_path, "POE-ROLE01", BOT_CHAT, None, None, 7, wait_seconds=0) is None
