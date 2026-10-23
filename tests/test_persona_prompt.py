"""Persona Card drafting and the `personas` command with a fake Claude client (T23, PLAN §4.2, ADR 0002)."""

from __future__ import annotations

import json
from dataclasses import fields
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from offer_engine import clock, personas
from offer_engine.cli import main
from offer_engine.commands import personas as personas_command
from offer_engine.customers import EVENT_DAYS, load_customer_state
from offer_engine.db import load_catalog
from offer_engine.sim.personas import draft, select
from offer_engine.sim.personas.draft import DraftError, ProfileSummary, build_summary, draft_card, user_prompt
from offer_engine.sim.personas.select import ShowcasePick
from tests.test_ground_truth_boundary import violations

GROUND_TRUTH_NAMES = {"base", "max_lift", "k", "response_class", "lift", "p_buy", "case", "in_holdout"}


class FakeClient:
    """Stands in for `anthropic.Anthropic`; each call returns the next canned card."""

    def __init__(
        self,
        names=("Asha Verma", "Ravi Nair", "Meena Iyer"),
        *,
        words=(80,),
        stop_reason="tool_use",
        content=None,
    ):
        self.messages = self
        self.words = list(words)
        self.calls = []
        self.names = list(names)
        self.stop_reason = stop_reason
        self.content = content

    def create(self, **kwargs):
        self.calls.append(kwargs)
        name = self.names[(len(self.calls) - 1) % len(self.names)]
        words = self.words[(len(self.calls) - 1) % len(self.words)]
        card = f"{name} shops for groceries.   " + " ".join(["more"] * (words - 5))
        tool_input = {"name": name, "card": card}
        content = self.content or [SimpleNamespace(type="tool_use", name=draft.TOOL_NAME, input=tool_input)]
        return SimpleNamespace(stop_reason=self.stop_reason, content=content)


def summary_of(world, customer_id):
    state = load_customer_state(world, customer_id, clock.START)
    return build_summary(state, load_catalog(world), clock.START)


def first_buyer(world) -> str:
    return world.execute(
        "SELECT customer_id FROM events WHERE kind = 'order' ORDER BY customer_id"
    ).fetchone()[0]


# --- The prompt builder sees observable data only ----------------------------------------------


def test_profile_summary_has_no_ground_truth_fields():
    names = {f.name for f in fields(ProfileSummary)}
    assert not {n for n in names if n.startswith("sim_")}
    assert not names & GROUND_TRUTH_NAMES


def test_draft_module_never_reads_simulator_tables():
    assert violations(Path(draft.__file__)) == []


def test_summary_and_prompt_come_from_the_customers_data(world):
    cid = first_buyer(world)
    summary = summary_of(world, cid)
    orders = world.execute(
        "SELECT COUNT(*) FROM events WHERE customer_id = ? AND kind = 'order' AND at >= ?",
        (cid, (clock.START - timedelta(days=EVENT_DAYS)).isoformat()),
    ).fetchone()[0]
    assert summary.customer_id == cid
    assert summary.orders == orders
    prompt = user_prompt(summary, others=("Asha Verma, 34, teaches in Pune.",))
    assert f"## Customer {cid}" in prompt
    assert "## Other cards start like this\n- Asha Verma, 34, teaches in Pune." in prompt
    assert "sure_thing" not in prompt and "persuadable" not in prompt


def test_draft_card_returns_the_tool_input_with_whitespace_squeezed(world):
    client = FakeClient()
    result = draft_card(client, "test-model", summary_of(world, first_buyer(world)))
    assert result.name == "Asha Verma"
    assert result.card.startswith("Asha Verma shops for groceries. more more")
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["model"] == "test-model"
    assert call["tools"] == [draft.TOOL]
    assert call["tool_choice"]["type"] == "auto"


def test_card_outside_60_to_100_words_is_asked_for_once_more(world):
    client = FakeClient(names=("Long Card", "Fixed Card"), words=(130, 90))
    result = draft_card(client, "test-model", summary_of(world, first_buyer(world)))
    assert result.name == "Fixed Card"
    assert "came out at 130 words" in client.calls[1]["messages"][0]["content"]


def test_second_attempt_is_kept_whatever_its_length(world):
    client = FakeClient(words=(30, 40, 80))
    result = draft_card(client, "test-model", summary_of(world, first_buyer(world)))
    assert len(client.calls) == draft.ATTEMPTS == 2
    assert len(result.card.split()) == 40


@pytest.mark.parametrize(
    "client, message",
    [
        (FakeClient(stop_reason="refusal"), "refused"),
        (FakeClient(stop_reason="max_tokens"), "cut off"),
        (FakeClient(content=[SimpleNamespace(type="text", text="hi")]), "didn't call"),
    ],
)
def test_draft_card_raises_on_unusable_answers(world, client, message):
    with pytest.raises(DraftError, match=message):
        draft_card(client, "test-model", summary_of(world, first_buyer(world)))


# --- The `personas` command ----------------------------------------------------------------------


@pytest.fixture
def setup(world, monkeypatch, tmp_path):
    """The command on the 50-Customer world with a fake client; `pick(*ids)` sets the showcase picks."""
    monkeypatch.setenv("DB_PATH", world.execute("PRAGMA database_list").fetchone()[2])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("OFFER_AGENT_MODEL", "test-model")
    monkeypatch.setenv("SEED", "7")
    client = FakeClient()
    monkeypatch.setattr(personas_command, "_client", lambda key: client)
    ids = [r[0] for r in world.execute("SELECT id FROM customers ORDER BY id LIMIT 3")]

    def pick(*customer_ids):
        chosen = [ShowcasePick(case, cid) for case, cid in zip(personas.CASES, customer_ids, strict=False)]
        monkeypatch.setattr(select, "select_showcase", lambda conn, rules, now: chosen)

    pick(ids[0], ids[1])
    return SimpleNamespace(dir=tmp_path / "personas", client=client, ids=ids, pick=pick)


def run(setup, *action):
    return main(["personas", *action, "--dir", str(setup.dir)])


def test_draft_saves_unfrozen_cards_with_the_seed(setup, world):
    assert run(setup, "draft") == 0
    saved = json.loads((setup.dir / f"{setup.ids[0]}.json").read_text())
    assert saved["customer_id"] == setup.ids[0]
    assert saved["case"] == personas.CASES[0]
    assert saved["name"] == "Asha Verma"
    assert saved["frozen"] is False
    assert saved["seed"] == 7
    assert saved["population"] == world.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    assert set(saved) == {"customer_id", "case", "name", "card", "frozen", "drafted_at", "seed", "population"}
    # The second card is shown how the first one starts, so it describes someone different.
    assert "- Asha Verma shops for groceries." in setup.client.calls[1]["messages"][0]["content"]


def test_freeze_flips_every_card(setup, capsys):
    run(setup, "draft")
    assert run(setup, "freeze") == 0
    assert all(c.frozen for c in personas.load_all(setup.dir))
    assert "froze 2 cards" in capsys.readouterr().out


def test_draft_skips_frozen_cards(setup):
    run(setup, "draft")
    path = setup.dir / f"{setup.ids[0]}.json"
    edited = personas.load(path).card + " Edited by a reviewer."
    personas.save(
        personas.PersonaCard(**{**json.loads(path.read_text()), "card": edited, "frozen": True}), setup.dir
    )
    calls = len(setup.client.calls)
    run(setup, "draft")
    assert len(setup.client.calls) == calls + 1  # only the unfrozen card was drafted again
    assert personas.load(path).card == edited


def test_draft_removes_stale_drafts_and_refuses_a_world_without_frozen_customers(setup):
    run(setup, "draft")
    setup.pick(setup.ids[0], setup.ids[2])
    run(setup, "draft")
    assert sorted(p.stem for p in setup.dir.glob("*.json")) == [setup.ids[0], setup.ids[2]]

    run(setup, "freeze")
    setup.pick(setup.ids[1])
    with pytest.raises(SystemExit, match="frozen card"):
        run(setup, "draft")


def test_draft_needs_the_api_key(setup, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setattr("offer_engine.config.DEFAULT_ENV_FILE", Path("/nonexistent/.env"))
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        run(setup, "draft")


def test_show_lists_cards_in_case_order(setup, capsys):
    run(setup, "draft")
    capsys.readouterr()
    assert run(setup, "show") == 0
    out = capsys.readouterr().out
    assert out.index("At-risk high value") < out.index("New, one order")
    assert "Asha Verma [draft, 80 words]" in out
    assert "missing cases: deal_hunter" in out


def test_show_and_freeze_need_cards(setup):
    for action in ("show", "freeze"):
        with pytest.raises(SystemExit, match="no Persona Cards"):
            run(setup, action)
