"""Testers (T25, PLAN §4.1, QnA Q16): a human picks a Customer, plays their own copy of it and asks for Offers."""

from __future__ import annotations

import asyncio
import random
import re
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from offer_engine import clock, pipeline, testers
from offer_engine.customers import load_customer_state, population_filter
from offer_engine.domain import RuleSet
from offer_engine.lift.segment_lift import segment_of
from offer_engine.offer_bot import responses
from offer_engine.offer_bot.handlers import testers as handlers
from offer_engine.personas import PersonaCard, save
from offer_engine.rules import in_holdout

USER = 777
NOW = datetime(2026, 12, 1, 12, 0)


@pytest.fixture
def cards_dir(tmp_path):
    return tmp_path / "personas"


@pytest.fixture
def ids(world):
    """A Customer outside the Holdout with finished Offers, and one inside it."""
    clock.set_now(world, NOW)
    rows = world.execute(
        "SELECT c.id FROM customers c WHERE EXISTS (SELECT 1 FROM offers o WHERE o.customer_id = c.id"
        " AND o.status = 'redeemed') ORDER BY c.id"
    ).fetchall()
    outside = next(r[0] for r in rows if not in_holdout(r[0], RuleSet().holdout_pct))
    inside = next(
        r[0]
        for r in world.execute("SELECT id FROM customers ORDER BY id")
        if in_holdout(r[0], RuleSet().holdout_pct)
    )
    return SimpleNamespace(outside=outside, inside=inside)


@pytest.fixture
def cards(ids, cards_dir):
    """Frozen cards for both Customers, plus a draft and one for a Customer not in this world."""
    made = {
        "cart_abandoner": PersonaCard(
            ids.outside, "cart_abandoner", "Asha Rao", "Asha shops at night.", True, "", 7, 50
        ),
        "holdout": PersonaCard(
            ids.inside, "holdout", "Vikram Shah", "Vikram buys every week.", True, "", 7, 50
        ),
    }
    for card in made.values():
        save(card, cards_dir)
    save(PersonaCard("C00049", "deal_hunter", "Draft", "", False, "", 7, 50), cards_dir)
    save(PersonaCard("C99999", "sure_thing", "Elsewhere", "", True, "", 8, 50), cards_dir)
    return made


@pytest.fixture
def high_lift(monkeypatch):
    """Every option is worth sending, so the rules chooser always picks an Offer."""
    monkeypatch.setattr(pipeline, "default_lift_estimator", lambda conn, now: lambda state, option: 0.5)


def count(conn, sql, *params) -> int:
    return conn.execute(sql, params).fetchone()[0]


# --- Tester copies -----------------------------------------------------------------------------


def test_copy_is_created_once_per_customer_and_tester(world, ids):
    cid = testers.create_tester_copy(world, ids.outside, USER)
    assert cid == f"{ids.outside}-t{USER}"
    assert testers.create_tester_copy(world, ids.outside, USER) == cid
    other = testers.create_tester_copy(world, ids.outside, 888)
    assert other != cid
    row = world.execute("SELECT * FROM customers WHERE id = ?", (cid,)).fetchone()
    source = world.execute("SELECT * FROM customers WHERE id = ?", (ids.outside,)).fetchone()
    assert (row["is_tester_copy"], row["source_customer_id"], row["opted_out"]) == (1, ids.outside, 0)
    assert (row["loyalty_tier"], row["points_balance"], row["points_expire_at"]) == (
        source["loyalty_tier"],
        source["points_balance"],
        source["points_expire_at"],
    )
    assert count(world, "SELECT COUNT(*) FROM customers WHERE source_customer_id = ?", ids.outside) == 2


def test_copy_shares_the_sources_holdout(world, ids):
    for source in (ids.outside, ids.inside):
        cid = testers.create_tester_copy(world, source, USER)
        assert in_holdout(cid, 10.0) == in_holdout(source, 10.0)


def test_copy_gets_the_last_180_days_of_events(world, ids):
    cid = testers.create_tester_copy(world, ids.outside, USER)
    since = (NOW - timedelta(days=180)).isoformat()
    window = "customer_id = ? AND at >= ? AND at <= ?"
    assert count(world, f"SELECT COUNT(*) FROM events WHERE {window}", cid, since, NOW.isoformat()) == count(
        world, f"SELECT COUNT(*) FROM events WHERE {window}", ids.outside, since, NOW.isoformat()
    )
    assert count(world, "SELECT COUNT(*) FROM events WHERE customer_id = ? AND at < ?", cid, since) == 0


def test_copy_gets_every_past_offer_whatever_its_age(world, ids):
    """The pipeline reads every past Offer (coupon-user segment, caps, the agent's prompt), not 180 days of them."""
    cid = testers.create_tester_copy(world, ids.outside, USER)
    copied = world.execute("SELECT * FROM offers WHERE customer_id = ? ORDER BY id", (cid,)).fetchall()
    originals = world.execute(
        "SELECT * FROM offers WHERE customer_id = ? AND created_at <= ? ORDER BY id",
        (ids.outside, NOW.isoformat()),
    ).fetchall()
    assert min(o["created_at"] for o in originals) < (NOW - timedelta(days=180)).isoformat()
    assert copied and len(copied) == len(originals)
    for new, old in zip(copied, originals, strict=True):
        assert new["code"] != old["code"] and new["code"].startswith("POE-")
        assert [new[k] for k in ("offer_type", "status", "created_at", "expires_at", "redeemed_at")] == [
            old[k] for k in ("offer_type", "status", "created_at", "expires_at", "redeemed_at")
        ]
    # Events point at the copy's own Offers, never the source's.
    mine = {row["id"] for row in copied}
    linked = {
        r[0]
        for r in world.execute(
            "SELECT offer_id FROM events WHERE customer_id = ? AND offer_id IS NOT NULL", (cid,)
        )
    }
    assert linked and linked <= mine


def test_copy_has_the_sources_lift_segment(world, ids):
    cid = testers.create_tester_copy(world, ids.outside, USER)
    source, copy = (load_customer_state(world, c, NOW) for c in (ids.outside, cid))
    assert segment_of(copy, NOW) == segment_of(source, NOW)
    assert segment_of(source, NOW)[2], "the fixture Customer should be a coupon user"


def test_open_offers_stay_with_the_source(world, ids):
    world.execute(
        "UPDATE offers SET status = 'claimed', created_at = ?, expires_at = ? WHERE id = (SELECT MAX(id) FROM offers"
        " WHERE customer_id = ?)",
        ((NOW - timedelta(days=1)).isoformat(), (NOW + timedelta(days=2)).isoformat(), ids.outside),
    )
    world.commit()
    cid = testers.create_tester_copy(world, ids.outside, USER)
    open_since = (NOW - timedelta(days=1)).isoformat()
    assert (
        count(world, "SELECT COUNT(*) FROM offers WHERE customer_id = ? AND created_at = ?", cid, open_since)
        == 0
    )
    assert (
        count(world, "SELECT COUNT(*) FROM offers WHERE customer_id = ?", cid)
        == count(world, "SELECT COUNT(*) FROM offers WHERE customer_id = ?", ids.outside) - 1
    )


def test_a_copy_cannot_be_copied_and_unknown_customers_raise(world, ids):
    cid = testers.create_tester_copy(world, ids.outside, USER)
    with pytest.raises(ValueError):
        testers.create_tester_copy(world, cid, 888)
    with pytest.raises(KeyError):
        testers.create_tester_copy(world, "C99999", USER)


def test_switching_opts_the_old_copy_out_and_picking_it_again_opts_it_in(world, ids):
    first = testers.create_tester_copy(world, ids.outside, USER)
    world.execute(
        "INSERT INTO offers (code, customer_id, offer_type, created_at, send_at, expires_at, rule_version,"
        " worst_case_cost, expected_cost, status, source) VALUES ('POE-QUEUED', ?, 'nudge', ?, ?, ?, 1, 0, 0,"
        " 'queued', 'live')",
        (first, NOW.isoformat(), NOW.isoformat(), (NOW + timedelta(days=3)).isoformat()),
    )
    world.commit()
    second = testers.create_tester_copy(world, ids.inside, USER)
    assert testers.played_by(world, USER) == second
    assert count(world, "SELECT opted_out FROM customers WHERE id = ?", first) == 1
    assert count(world, "SELECT COUNT(*) FROM offers WHERE code = 'POE-QUEUED' AND status = 'withdrawn'") == 1
    assert count(world, "SELECT COUNT(*) FROM chats WHERE chat_id = ?", USER) == 1

    testers.create_tester_copy(world, ids.outside, USER)
    assert count(world, "SELECT opted_out FROM customers WHERE id = ?", first) == 0
    assert count(world, "SELECT opted_out FROM customers WHERE id = ?", second) == 1
    kinds = [
        r[0]
        for r in world.execute(
            "SELECT kind FROM events WHERE customer_id = ? AND at = ?", (first, NOW.isoformat())
        )
    ]
    assert kinds == ["opted_out", "opted_in"]


def test_population_filter_leaves_tester_copies_out(world, ids):
    population = count(world, "SELECT COUNT(*) FROM customers")
    testers.create_tester_copy(world, ids.outside, USER)
    assert count(world, f"SELECT COUNT(*) FROM customers WHERE {population_filter()}") == population
    assert count(world, f"SELECT COUNT(*) FROM customers c WHERE {population_filter('c')}") == population


# --- Picking -----------------------------------------------------------------------------------


def test_start_offers_frozen_cards_of_this_world_in_case_order(world, cards, cards_dir):
    reply, offered = handlers.start(world, USER, cards_dir)
    assert reply == handlers.WELCOME
    assert [c.name for c in offered] == ["Asha Rao", "Vikram Shah"]
    buttons = [row[0] for row in handlers.picker(offered).inline_keyboard]
    assert [(b.text, b.callback_data) for b in buttons] == [
        ("Asha Rao · Cart abandoner", f"pick:{cards['cart_abandoner'].customer_id}"),
        ("Vikram Shah · Holdout", f"pick:{cards['holdout'].customer_id}"),
        ("Surprise me", "pick:surprise"),
    ]
    assert all(re.match(handlers.PICK_PATTERN, b.callback_data) for b in buttons)


def test_start_turns_offers_back_on_for_a_stopped_tester(world, cards, cards_dir, ids):
    handlers.pick(world, ids.outside, USER, USER, cards_dir)
    responses.stop(world, USER)
    reply, offered = handlers.start(world, USER, cards_dir)
    assert reply.startswith(responses.RESTARTED) and offered
    assert count(world, "SELECT opted_out FROM customers WHERE id = ?", testers.played_by(world, USER)) == 0


def test_start_without_cards(world, cards_dir):
    assert handlers.start(world, USER, cards_dir) == (handlers.NO_CARDS, [])


def test_pick_creates_a_copy_and_shows_the_persona_card(world, cards, cards_dir, ids):
    reply = handlers.pick(world, ids.outside, USER, USER, cards_dir)
    assert reply == (
        "Asha shops at night.\n\nSimulated date: 1 Dec 2026. Offers arrive as the marketing team advances the clock. "
        "Send /offers to ask for one now."
    )
    assert testers.played_by(world, USER) == f"{ids.outside}-t{USER}"


def test_pick_holdout_explains_the_control_group(world, cards, cards_dir, ids):
    reply = handlers.pick(world, ids.inside, USER, USER, cards_dir)
    assert reply.endswith(
        "You're playing Vikram Shah, who is in the control group (Holdout). They never receive offers, so we can "
        "measure what offers change."
    )


def test_surprise_me_picks_one_of_the_playable_cards(world, cards, cards_dir, ids):
    reply = handlers.pick(world, handlers.SURPRISE, USER, USER, cards_dir, rng=random.Random(1))
    played = testers.played_by(world, USER)
    assert played in {f"{ids.outside}-t{USER}", f"{ids.inside}-t{USER}"}
    assert reply.startswith(("Asha shops", "Vikram buys"))


def test_pick_of_a_card_not_offered(world, cards, cards_dir):
    assert handlers.pick(world, "C00049", USER, USER, cards_dir) == handlers.UNKNOWN_PICK
    assert testers.played_by(world, USER) is None


# --- /offers and /whoami -----------------------------------------------------------------------


def test_offers_before_picking(world, cards_dir):
    assert handlers.request_offer(world, USER, cards_dir) == handlers.NOT_PLAYING
    assert handlers.whoami(world, USER, cards_dir) == handlers.NOT_PLAYING


def test_offers_runs_the_pipeline_on_request(world, cards, cards_dir, ids, high_lift):
    handlers.pick(world, ids.outside, USER, USER, cards_dir)
    reply = handlers.request_offer(world, USER, cards_dir)
    cid = testers.played_by(world, USER)
    decision = world.execute("SELECT * FROM decisions WHERE customer_id = ?", (cid,)).fetchone()
    assert decision["trigger"] == "on_request" and decision["offer_id"] is not None
    assert reply == "The engine picked an offer for Asha Rao. It's on its way."


def test_offers_outside_send_hours_says_when_it_goes_out(world, cards, cards_dir, ids, high_lift):
    clock.set_now(world, datetime(2026, 12, 1, 2, 0))
    handlers.pick(world, ids.outside, USER, USER, cards_dir)
    reply = handlers.request_offer(world, USER, cards_dir)
    assert re.fullmatch(
        r"The engine picked an offer for Asha Rao\. It goes out at 1 Dec, \d\d:\d\d simulated time, once the "
        r"marketing team advances the clock that far\.",
        reply,
    )


def test_offers_explains_no_offer_with_the_binding_rule(world, cards, cards_dir, ids, high_lift):
    handlers.pick(world, ids.outside, USER, USER, cards_dir)
    # The copy may carry recent Offers from the source; ask until the frequency cap binds.
    for _ in range(RuleSet().frequency_cap_count + 1):
        reply = handlers.request_offer(world, USER, cards_dir)
    assert reply == "No offer right now: Asha Rao already got 2 offers this week."


def test_offers_for_the_holdout(world, cards, cards_dir, ids):
    handlers.pick(world, ids.inside, USER, USER, cards_dir)
    assert handlers.request_offer(world, USER, cards_dir) == (
        "No offer right now: Vikram Shah is in the control group (Holdout), so they never receive offers."
    )


def test_whoami(world, cards, cards_dir, ids):
    handlers.pick(world, ids.outside, USER, USER, cards_dir)
    assert handlers.whoami(world, USER, cards_dir) == (
        f"You're playing Asha Rao (Cart abandoner), Customer {ids.outside}-t{USER}. Simulated date: 1 Dec 2026. "
        "Send /switch to pick someone else."
    )


@pytest.mark.parametrize(
    ("binding", "reason"),
    [
        ("opt_out", "Asha turned offers off. Send /start to turn them back on."),
        (
            "fatigue_dismissals",
            "Asha tapped Not now 3 times within 14 days, so offers are paused for 14 days.",
        ),
        ("frequency_cap_count", "Asha already got 2 offers this week."),
        ("cooldown_days_after_redemption", "Asha used an offer in the last 7 days, so the next one waits."),
        ("min_days_since_signup", "Asha signed up less than 1 day ago."),
        (pipeline.FALLBACK_FAILED, "the engine couldn't find an offer that passes every Rule."),
        (None, "none of the offers the Rules allow is worth its cost for Asha."),
    ],
)
def test_no_offer_reason(binding, reason):
    assert handlers.no_offer_reason("Asha", binding, RuleSet()) == reason


def test_no_offer_reason_frequency_cap_other_than_a_week():
    rules = replace(RuleSet(), frequency_cap_count=1, frequency_cap_days=3)
    assert (
        handlers.no_offer_reason("Asha", "frequency_cap_count", rules)
        == "Asha already got 1 offer in the last 3 days."
    )


# --- Telegram handlers -------------------------------------------------------------------------


class FakeMessage:
    def __init__(self, chat_id):
        self.chat = SimpleNamespace(id=chat_id)
        self.replies: list[tuple[str, object]] = []

    async def reply_text(self, text, reply_markup=None):
        self.replies.append((text, reply_markup))


def fake_update(chat_id, is_bot=False):
    message = FakeMessage(chat_id)
    user = SimpleNamespace(id=chat_id, is_bot=is_bot)
    return SimpleNamespace(
        effective_user=user, effective_chat=message.chat, effective_message=message
    ), message


def fake_context(tmp_path, cards_dir, match=None):
    settings = SimpleNamespace(db_path=tmp_path / "world.db")
    return SimpleNamespace(bot_data={"settings": settings, "personas_dir": cards_dir}, matches=[match])


def test_on_start_from_a_human_sends_the_picker(world, cards, cards_dir, tmp_path):
    update, message = fake_update(USER)
    asyncio.run(handlers.on_start(update, fake_context(tmp_path, cards_dir)))
    [(text, markup)] = message.replies
    assert text == handlers.WELCOME
    assert markup.inline_keyboard[-1][0].text == "Surprise me"


def test_on_start_from_a_customer_bot_only_opts_back_in(world, cards, cards_dir, tmp_path, ids):
    bot_chat = 4242
    world.execute(
        "INSERT INTO chats (customer_id, chat_id, kind) VALUES (?, ?, 'bot')", (ids.outside, bot_chat)
    )
    world.commit()
    responses.stop(world, bot_chat)
    update, message = fake_update(bot_chat, is_bot=True)
    asyncio.run(handlers.on_start(update, fake_context(tmp_path, cards_dir)))
    assert message.replies == [(responses.RESTARTED, None)]
    assert count(world, "SELECT COUNT(*) FROM customers WHERE is_tester_copy = 1") == 0


def test_on_pick_then_on_offers(world, cards, cards_dir, tmp_path, ids):
    message = FakeMessage(USER)
    calls = []

    async def answer():
        calls.append("answer")

    async def edit_message_reply_markup(reply_markup):
        calls.append(("edit", reply_markup))

    query = SimpleNamespace(
        from_user=SimpleNamespace(id=USER),
        message=message,
        answer=answer,
        edit_message_reply_markup=edit_message_reply_markup,
    )
    match = re.match(handlers.PICK_PATTERN, f"pick:{ids.inside}")
    asyncio.run(
        handlers.on_pick(SimpleNamespace(callback_query=query), fake_context(tmp_path, cards_dir, match))
    )
    assert calls == ["answer", ("edit", None)]
    assert "control group (Holdout)" in message.replies[0][0]

    update, message = fake_update(USER)
    asyncio.run(handlers.on_offers(update, fake_context(tmp_path, cards_dir)))
    assert message.replies[0][0].startswith("No offer right now: Vikram Shah is in the control group")


def test_start_pattern_matches_text_starts():
    for text, ok in [("/start", True), ("/START@poe_offer_bot", True), ("/start now", False)]:
        assert bool(re.match(handlers.START_PATTERN, text)) is ok
