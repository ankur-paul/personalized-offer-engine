"""Every demo scenario passes on the 10k seed-7 snapshot with recorded agent answers and no API key (T37)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from offer_engine import config, pipeline
from offer_engine.demo import runner, snapshot
from offer_engine.demo.replay import ReplayClient

pytestmark = [
    pytest.mark.demo,
    pytest.mark.skipif(not snapshot.DEFAULT_PATH.is_file(), reason="no data/demo.db; run `demo snapshot`"),
]


def test_every_scenario_passes_under_replay(monkeypatch):
    # Replay only: with no key, a missing recording can't reach Claude.
    monkeypatch.setattr(
        pipeline,
        "load_settings",
        lambda: replace(config.load_settings(), anthropic_api_key=None, agent_mode="replay", demo_seed=None),
    )
    pipeline._client.cache_clear()
    monkeypatch.setattr(
        runner,
        "roleplay_agent",
        lambda: (ReplayClient(None, "replay"), config.load_settings().fast_agent_model),
    )
    results = runner.check()
    assert [(r.scenario.name, r.mismatches) for r in results] == [(r.scenario.name, ()) for r in results]
    # The recorded answers were used: the agent's, not the Fallback's, and the Customer Bot's message fit.
    nudge = next(r for r in results if r.scenario.name == "lost-cause-nudge")
    assert nudge.decision.chooser == "agent" and nudge.fit != 0
