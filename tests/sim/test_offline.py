"""Offline Policy runs (T26) on a 300-Customer world, with a fake agent."""

import json
import math
import re
import shutil
import threading
from datetime import timedelta
from types import SimpleNamespace

import pytest

from offer_engine import clock, pipeline
from offer_engine.cli import main
from offer_engine.customers import load_customer_state
from offer_engine.db import connect, load_catalog, migrate
from offer_engine.domain import Event, OfferType, PastOffer, RuleSet, TriggerKind
from offer_engine.lift import segment_lift
from offer_engine.rules import in_holdout
from offer_engine.sim import agent_cache, offline
from offer_engine.sim.metrics import summarise
from offer_engine.sim.policies import POLICIES, AgentForSample, RunContext, blanket_choose, top_category
from offer_engine.sim.world import day_step

DAYS = 5
WORLD_TABLES = (
    "customers",
    "events",
    "offers",
    "decisions",
    "clock",
    "sim_pending_events",
    "sim_offer_fates",
)


class FakeAgent:
    """Stands in for `anthropic.Anthropic`: always picks the Nudge from the Eligible Set it is shown."""

    def __init__(self):
        self.messages = self
        self.calls = 0
        self.lock = threading.Lock()

    def create(self, **kwargs):
        with self.lock:
            self.calls += 1
        prompt = kwargs["messages"][0]["content"]
        index = int(re.search(r"^\[(\d+)\] nudge:", prompt, re.MULTILINE).group(1))
        tool_input = {
            "option_index": index,
            "params": dict.fromkeys(("pct", "cap", "amount", "min_basket", "multiplier")),
            "featured_product_ids": [],
            "caption": "Your picks are still waiting for you.",
            "reason": "a Nudge is enough",
        }
        block = SimpleNamespace(type="tool_use", name="propose_offer", input=tool_input)
        return SimpleNamespace(stop_reason="tool_use", content=[block])


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    from offer_engine.sim.generate import run

    path = tmp_path_factory.mktemp("offline") / "world.db"
    conn = connect(path)
    run(conn, 300, months=6, seed=7)
    segment_lift.fit(conn)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    return path


@pytest.fixture
def src(template, tmp_path):
    path = tmp_path / "world.db"
    shutil.copy(template, path)
    return path


def snapshot(path):
    conn = connect(path)
    out = {t: conn.execute(f"SELECT COUNT(*), MAX(rowid) FROM {t}").fetchone()[:] for t in WORLD_TABLES}
    out["now"] = clock.now(conn)
    conn.close()
    return out


def sample_of(path, n=60):
    conn = connect(path)
    sample = offline.stratified_sample(conn, n, 7)
    conn.close()
    return sample


# --- Runs ----------------------------------------------------------------------------------------


def test_no_offers_spends_nothing_and_leaves_the_source_unchanged(src):
    before = snapshot(src)
    result = offline.run_policy(src, "no_offers", DAYS, seed=3)
    assert snapshot(src) == before
    assert result.offers == [] and len(result.margin) == 300
    m = summarise(result, result, list(result.margin), "population")
    assert m.spend == 0 and m.incremental_margin == 0 and m.offers_sent == 0
    assert not list(src.parent.glob(".sim-*"))


def test_same_seed_gives_identical_results(src):
    first = offline.run_policy(src, "rules_only", DAYS, seed=3)
    second = offline.run_policy(src, "rules_only", DAYS, seed=3)
    assert first.offers and first.margin == second.margin and first.offers == second.offers


def test_rules_only_spends_and_is_scored_against_no_offers(src):
    baseline = offline.run_policy(src, "no_offers", DAYS, seed=3)
    rules = offline.run_policy(src, "rules_only", DAYS, seed=3)
    m = summarise(rules, baseline, list(baseline.margin), "population")
    assert m.offers_sent > 0 and m.redeemed > 0 and m.spend > 0
    assert m.per_rupee == pytest.approx(m.incremental_margin / m.spend)
    assert m.lift_deciles and all(d.offers > 0 for d in m.lift_deciles)
    assert all(o.true_lift is not None for o in rules.offers if o.sent)


def test_blanket_sends_uncapped_20_percent_one_live_offer_at_a_time(src):
    result = offline.run_policy(src, "blanket_20", DAYS, seed=3)
    assert result.offers and {o.offer_type for o in result.offers} == {OfferType.PCT_CATEGORY}
    assert not any(in_holdout(o.customer_id, RuleSet().holdout_pct) for o in result.offers)

    # The same run kept open: no Offer is created while the Customer holds an earlier one that is still live.
    conn = connect(src)
    offline.prepare(conn)
    start = clock.now(conn)
    blanket = POLICIES["blanket_20"]
    with pipeline.chooser_override(blanket.chooser_factory(RunContext()), validate=False):
        day_step.advance(conn, DAYS * 24, 3)
    overlapping = conn.execute(
        "SELECT COUNT(*) FROM offers o JOIN offers p ON p.customer_id = o.customer_id AND p.id < o.id "
        "WHERE o.created_at >= ? AND p.expires_at > o.created_at AND p.status != 'withdrawn' "
        "AND (p.redeemed_at IS NULL OR p.redeemed_at > o.created_at) AND NOT EXISTS (SELECT 1 FROM events e "
        "WHERE e.offer_id = p.id AND e.kind = 'offer_dismissed' AND e.at <= o.created_at)",
        (start.isoformat(),),
    ).fetchone()[0]
    params = {
        r[0] for r in conn.execute("SELECT params FROM offers WHERE created_at >= ?", (start.isoformat(),))
    }
    conn.close()
    assert overlapping == 0
    assert {json.dumps(json.loads(p)) for p in params} == {json.dumps({"pct": 20.0, "cap": math.inf})}


def test_rerun_with_the_cache_makes_no_agent_calls(src):
    sample = sample_of(src)
    first = FakeAgent()
    result = offline.run_policy(src, "rules_plus_agent", DAYS, 3, sample, client=first, model="fake")
    assert first.calls > 0 and result.agent_calls == first.calls
    sampled = [o for o in result.offers if o.customer_id in sample]
    assert sampled and {o.offer_type for o in sampled} == {OfferType.NUDGE}
    assert {o.offer_type for o in result.offers if o.customer_id not in sample} - {OfferType.NUDGE}

    again = FakeAgent()
    rerun = offline.run_policy(src, "rules_plus_agent", DAYS, 3, sample, client=again, model="fake")
    assert again.calls == 0 and rerun.agent_calls == 0
    assert rerun.offers == result.offers and rerun.margin == result.margin


def test_rules_plus_agent_needs_an_agent(src):
    with pytest.raises(ValueError, match="needs an agent"):
        offline.run_policy(src, "rules_plus_agent", 1, 3, sample_of(src))


def test_stratified_sample_follows_the_segments(src):
    conn = connect(src)
    sample = offline.stratified_sample(conn, 60, 7)
    assert len(sample) == len(set(sample)) == 60 and sample == offline.stratified_sample(conn, 60, 7)
    now = clock.now(conn)
    ids = [r[0] for r in conn.execute("SELECT id FROM customers")]
    states = {cid: load_customer_state(conn, cid, now) for cid in ids}
    conn.close()
    segment = {cid: segment_lift.segment_of(s, now) for cid, s in states.items()}
    for seg in set(segment.values()):
        share = sum(segment[c] == seg for c in ids) / len(ids)
        assert abs(sum(segment[c] == seg for c in sample) - 60 * share) < 1


def test_tester_copies_get_nothing_and_chat_customers_are_settled_like_the_rest(src):
    from offer_engine.testers import create_tester_copy

    conn = connect(src)
    ids = [r[0] for r in conn.execute("SELECT id FROM customers ORDER BY id")]
    source, bot = [cid for cid in ids if not in_holdout(cid, RuleSet().holdout_pct)][:2]
    copy_id = create_tester_copy(conn, source, 42)
    conn.execute("INSERT INTO chats VALUES (?, 99, 'bot')", (bot,))
    conn.commit()
    conn.close()
    result = offline.run_policy(src, "blanket_20", DAYS, seed=3)
    assert copy_id not in result.margin and all(o.customer_id != copy_id for o in result.offers)
    bot_offers = [o for o in result.offers if o.customer_id == bot]
    assert bot_offers and all(o.sent and o.true_lift is not None for o in bot_offers)


# --- Policies --------------------------------------------------------------------------------------


def test_blanket_choose_skips_customers_with_a_live_offer(src):
    conn = connect(src)
    now = clock.now(conn)
    catalog = load_catalog(conn)
    cid = conn.execute(
        "SELECT customer_id FROM events WHERE kind = 'order' ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    state = load_customer_state(conn, cid, now)
    conn.close()
    es = SimpleNamespace(at=now, send_window=None)
    proposal = blanket_choose(es, state, catalog, RuleSet())
    assert proposal.offer_type == OfferType.PCT_CATEGORY and proposal.params == {"pct": 20.0, "cap": math.inf}
    assert proposal.category == top_category(state, now, catalog) and proposal.send_at == now

    live = PastOffer(1, OfferType.NUDGE, None, "sent", now - timedelta(days=1), now + timedelta(days=2))
    held = SimpleNamespace(**{**state.__dict__, "offers": (*state.offers, live)})
    assert blanket_choose(es, held, catalog, RuleSet()).offer_type is None
    expired = SimpleNamespace(
        **{
            **state.__dict__,
            "offers": (
                *state.offers,
                PastOffer(1, OfferType.NUDGE, None, "sent", now - timedelta(days=4), now - timedelta(days=1)),
            ),
        }
    )
    assert blanket_choose(es, expired, catalog, RuleSet()).offer_type == OfferType.PCT_CATEGORY


def test_top_category_prefers_orders_then_any_event():
    catalog = SimpleNamespace(categories={"books": None, "fashion": None, "grocery": None})
    now = clock.START

    def ev(kind, category, days_ago=1):
        return Event("c", now - timedelta(days=days_ago), kind, category)

    state = SimpleNamespace(
        events=(ev("order", "books"), ev("product_view", "fashion"), ev("product_view", "fashion"))
    )
    assert top_category(state, now, catalog) == "books"
    state = SimpleNamespace(events=(ev("product_view", "fashion"), ev("order", "grocery", days_ago=200)))
    assert top_category(state, now, catalog) == "fashion"
    assert top_category(SimpleNamespace(events=()), now, catalog) == "books"


def test_agent_for_sample_routes_only_the_sample_to_the_agent(src):
    conn = connect(src)
    migrate(conn)
    cache = agent_cache.AgentCache(conn, FakeAgent(), "fake")
    factory = AgentForSample(RunContext(frozenset({"C1"}), cache))
    inside = SimpleNamespace(customer=SimpleNamespace(id="C1"))
    outside = SimpleNamespace(customer=SimpleNamespace(id="C2"))
    assert isinstance(factory(inside, TriggerKind.DAILY_SWEEP), agent_cache.CachedAgentChooser)
    assert factory(outside, TriggerKind.DAILY_SWEEP) is pipeline.rules_chooser.choose
    conn.close()


def test_cached_answers_go_through_validation_like_fresh_ones(src):
    """A cached answer outside the Eligible Set still falls back."""
    conn = connect(src)
    migrate(conn)
    now = clock.now(conn)
    cid = next(
        r[0]
        for r in conn.execute("SELECT id FROM customers ORDER BY id")
        if not in_holdout(r[0], RuleSet().holdout_pct)
    )
    cache = agent_cache.AgentCache(conn, FakeAgent(), "fake")
    chooser = cache.chooser(TriggerKind.CART_ABANDONED)
    with pipeline.chooser_override(lambda state, trigger: chooser):
        pipeline.decide(conn, cid, TriggerKind.CART_ABANDONED, now)
    (raw,) = conn.execute("SELECT response FROM sim_agent_cache").fetchone()
    bad = {**json.loads(raw), "option_index": 99}
    conn.execute("UPDATE sim_agent_cache SET response = ?", (json.dumps(bad),))
    conn.execute("DELETE FROM decisions")
    conn.execute("DELETE FROM offers WHERE source = 'live'")
    conn.commit()
    with pipeline.chooser_override(lambda state, trigger: chooser):
        d = pipeline.decide(conn, cid, TriggerKind.CART_ABANDONED, now)
    assert d.chooser == "fallback" and cache.calls == 1
    conn.close()


# --- CLI -------------------------------------------------------------------------------------------


def test_cli_prints_the_table_and_saves_it(src, clean_env, monkeypatch, capsys):
    monkeypatch.setenv("DB_PATH", str(src))
    assert (
        main(
            [
                "simulate",
                "--policies",
                "rules_only,blanket_20",
                "--days",
                "2",
                "--sample",
                "40",
                "--jobs",
                "1",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "per ₹ spend" in out and "Rules Only" in out and "Blanket 20%" in out and "No Offers" in out
    conn = connect(src)
    rows = conn.execute("SELECT policy, scope FROM sim_policy_results ORDER BY id").fetchall()
    conn.close()
    assert [tuple(r) for r in rows] == [
        (p, s) for p in ("no_offers", "blanket_20", "rules_only") for s in ("population", "sample")
    ]


def test_cli_rejects_unknown_policies(src, clean_env, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(src))
    with pytest.raises(SystemExit, match="unknown Policies: nope"):
        main(["simulate", "--policies", "nope"])
    assert set(POLICIES) == {"no_offers", "blanket_20", "rules_only", "rules_plus_agent"}
