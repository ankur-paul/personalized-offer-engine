"""Recorded Claude answers played back for the demo (T36, QnA Q45)."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace

import numpy as np
import pytest

from offer_engine import pipeline
from offer_engine.config import Settings
from offer_engine.customer_sim import roleplay
from offer_engine.customer_sim.app import agent_client
from offer_engine.db import connect
from offer_engine.demo.replay import ReplayClient, ReplayMiss, request_key
from offer_engine.domain import Chooser
from tests import test_agent_chooser, test_roleplay
from tests.test_agent_chooser import CART, NOW, good_input
from tests.test_agent_chooser import FakeClient as AgentFake
from tests.test_roleplay import FakeClient as RoleplayFake
from tests.test_roleplay import persona, response_row

# Fixtures shared with the agent chooser and role-play tests.
customer_id = test_agent_chooser.customer_id
bot_offer = test_roleplay.bot_offer

REQUEST = {
    "model": "m",
    "max_tokens": 100,
    "system": "Be brief.",
    "tools": [{"name": "propose_offer"}],
    "messages": [{"role": "user", "content": "Hi"}],
    "timeout": 30,
}


@pytest.fixture
def recordings(tmp_path):
    return tmp_path / "demo" / "agent_recordings.jsonl"


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_record_calls_through_and_writes_the_answer_down(recordings):
    real = AgentFake({"option_index": 0})
    response = ReplayClient(real, "record", recordings).messages.create(**REQUEST)
    assert len(real.calls) == 1 and response.content[0].input == {"option_index": 0}
    [entry] = lines(recordings)
    assert entry["key"] == request_key(REQUEST) and entry["model"] == "m"
    assert entry["request"] == {k: REQUEST[k] for k in ("model", "system", "tools", "messages")}
    assert entry["response"] == {
        "stop_reason": "tool_use",
        "content": [{"type": "tool_use", "name": "propose_offer", "input": {"option_index": 0}}],
    }


def test_replay_returns_the_recorded_answer_without_a_call(recordings):
    ReplayClient(AgentFake({"option_index": 2}), "record", recordings).messages.create(**REQUEST)
    real = AgentFake({"option_index": 9})
    response = ReplayClient(real, "replay", recordings).messages.create(**{**REQUEST, "timeout": 5})
    assert real.calls == []
    assert response.stop_reason == "tool_use"
    block = response.content[0]
    assert (block.type, block.name, block.input, block.text) == (
        "tool_use",
        "propose_offer",
        {"option_index": 2},
        None,
    )


def test_replay_reads_answers_recorded_after_it_started(recordings):
    replay = ReplayClient(None, "replay", recordings)
    with pytest.raises(ReplayMiss):
        replay.messages.create(**REQUEST)
    ReplayClient(AgentFake({"option_index": 1}), "record", recordings).messages.create(**REQUEST)
    assert replay.messages.create(**REQUEST).content[0].input == {"option_index": 1}


def test_a_different_prompt_calls_through_and_records(recordings):
    ReplayClient(AgentFake({"option_index": 0}), "record", recordings).messages.create(**REQUEST)
    other = {**REQUEST, "messages": [{"role": "user", "content": "Hello"}]}
    real = AgentFake({"option_index": 3})
    replay = ReplayClient(real, "replay", recordings)
    assert replay.messages.create(**other).content[0].input == {"option_index": 3}
    assert len(real.calls) == 1 and len(lines(recordings)) == 2
    assert replay.messages.create(**other).content[0].input == {"option_index": 3}
    assert len(real.calls) == 1


def test_a_different_prompt_without_a_client_raises(recordings):
    ReplayClient(AgentFake({"option_index": 0}), "record", recordings).messages.create(**REQUEST)
    with pytest.raises(ReplayMiss):
        ReplayClient(None, "replay", recordings).messages.create(**{**REQUEST, "model": "other"})


def test_live_calls_through_and_records_nothing(recordings):
    real = AgentFake({"option_index": 0})
    ReplayClient(real, "live", recordings).messages.create(**REQUEST)
    assert len(real.calls) == 1 and not recordings.exists()


def test_a_half_written_line_waits_for_its_newline(recordings):
    ReplayClient(AgentFake({"option_index": 0}), "record", recordings).messages.create(**REQUEST)
    with recordings.open("a") as f:
        f.write('{"key": "unfinished')
    replay = ReplayClient(None, "replay", recordings)
    assert replay.messages.create(**REQUEST).content[0].input == {"option_index": 0}


def test_an_unknown_mode_is_refused(recordings):
    with pytest.raises(ValueError, match="live, replay, record"):
        ReplayClient(None, "sometimes", recordings)


# --- The offer agent ---------------------------------------------------------------------------


@pytest.fixture
def replay_settings(monkeypatch, tmp_path):
    """The pipeline's own `_client` in `mode`, with no API key, reading recordings under tmp_path."""
    monkeypatch.chdir(tmp_path)
    pipeline._client.cache_clear()

    def use(mode, api_key=None):
        settings = Settings(anthropic_api_key=api_key, offer_agent_model="test-model", agent_mode=mode)
        monkeypatch.setattr(pipeline, "load_settings", lambda: settings)

    yield use
    pipeline._client.cache_clear()


def test_the_agent_chooser_accepts_a_replayed_answer(
    world, world_template, tmp_path, customer_id, monkeypatch
):
    raw = good_input(world, customer_id)
    recordings = tmp_path / "rec.jsonl"
    monkeypatch.setattr(
        pipeline, "_client", lambda key, mode: ReplayClient(AgentFake(raw), "record", recordings)
    )
    monkeypatch.setattr(
        pipeline, "load_settings", lambda: Settings(anthropic_api_key="k", offer_agent_model="m")
    )
    recorded = pipeline.decide(world, customer_id, CART, NOW)

    # The same Decision on a fresh copy of the world, with no client behind the replay.
    copy = tmp_path / "copy.db"
    shutil.copy(world_template, copy)
    again = connect(copy)
    again.execute("INSERT INTO chats VALUES (?, 777, 'bot')", (customer_id,))
    again.commit()
    monkeypatch.setattr(pipeline, "_client", lambda key, mode: ReplayClient(None, "replay", recordings))
    replayed = pipeline.decide(again, customer_id, CART, NOW)
    assert replayed.chooser == recorded.chooser == Chooser.AGENT
    assert replayed.reason == recorded.reason == raw["reason"]
    caption = "SELECT caption FROM offers WHERE id = ?"
    assert again.execute(caption, (replayed.offer_id,)).fetchone()[0] == raw["caption"]
    again.close()


def test_replay_without_a_key_uses_the_agent(world, customer_id, replay_settings, tmp_path):
    raw = good_input(world, customer_id)
    replay_settings("replay")
    client = pipeline._client(None, "replay")
    assert isinstance(client, ReplayClient) and client.real is None
    # Record what the agent will be asked, by asking once with a client behind it.
    client.real = AgentFake(raw)
    first = pipeline.decide(world, customer_id, CART, NOW)
    client.real = None
    assert first.chooser == Chooser.AGENT
    assert (tmp_path / "demo" / "agent_recordings.jsonl").is_file()


def test_a_replay_miss_without_a_key_falls_back(world, customer_id, replay_settings):
    replay_settings("replay")
    d = pipeline.decide(world, customer_id, CART, NOW)
    assert d.chooser == Chooser.FALLBACK and d.validation.ok
    failures = json.loads(
        world.execute("SELECT validation_failures FROM decisions WHERE id = ?", (d.id,)).fetchone()[0]
    )
    assert any(f.startswith("chooser_error: ReplayMiss") for f in failures)


def test_live_mode_keeps_the_plain_client(replay_settings):
    assert pipeline._client(None, "live") is None


# --- Customer Bots -----------------------------------------------------------------------------


def test_rate_fit_accepts_a_replayed_answer(recordings):
    real = RoleplayFake({"fit": 0.8, "reply_claim": "Haan, le leti hoon!", "reply_not_now": "Abhi nahi."})
    args = ("fast-model", "Meera shops for kurtas.", "Your picks await.", ["20% off"])
    recorded = roleplay.rate_fit(ReplayClient(real, "record", recordings), *args)
    replayed = roleplay.rate_fit(ReplayClient(None, "replay", recordings), *args)
    assert replayed == recorded and replayed[0] == 0.8 and len(real.calls) == 1


def test_a_customer_bot_replay_miss_flips_on_ground_truth(world, bot_offer, recordings):
    offer = bot_offer()
    client = ReplayClient(None, "replay", recordings)
    roleplay.react(world, offer, persona(offer["customer_id"]), client, "m", np.random.default_rng(0))
    row = response_row(world, offer["id"])
    assert row["fit"] == 0 and row["p_used"] == row["p_base"]


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, type(None)),
        ({"agent_mode": "replay"}, ReplayClient),
        ({"agent_mode": "replay", "fast_agent_model": None}, type(None)),
        ({"agent_mode": "record", "anthropic_api_key": "k"}, ReplayClient),
        ({"agent_mode": "live", "anthropic_api_key": "k"}, object),
    ],
)
def test_customer_bot_client_by_mode(changes, expected):
    settings = replace(Settings(fast_agent_model="fast"), **changes)
    client = agent_client(settings)
    assert isinstance(client, expected)
    assert not isinstance(client, ReplayClient) or client.mode == settings.agent_mode
