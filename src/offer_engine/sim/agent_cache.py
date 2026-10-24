"""The agent's answers in offline Policy runs (T26), cached in `sim_agent_cache` so reruns cost nothing.

The key hashes everything the agent is sent, so a cached answer is reused only for the same request. A cached
answer goes through `to_proposal` as a fresh one does, so the pipeline validates it the same way.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from offer_engine.choosers.agent_chooser import (
    EFFORT,
    SYSTEM_PROMPT,
    TOOL,
    AgentChooser,
    to_proposal,
    user_prompt,
)
from offer_engine.domain import Catalog, CustomerState, EligibleSet, Proposal, RuleSet, TriggerKind

PREFETCH_WORKERS = 16


def request_hash(model: str, user_message: str) -> str:
    request = {"model": model, "system": SYSTEM_PROMPT, "tool": TOOL, "effort": EFFORT, "user": user_message}
    return hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()


class AgentCache:
    """`sim_agent_cache` on `conn`, counting the calls that missed it."""

    def __init__(self, conn: sqlite3.Connection, client: Any, model: str):
        self.conn = conn
        self.client = client
        self.model = model
        self.calls = 0

    def get(self, key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT response FROM sim_agent_cache WHERE prompt_hash = ?", (key,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, raw: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO sim_agent_cache (prompt_hash, model, response, created_at) VALUES (?, ?, ?, ?)",
            (
                key,
                self.model,
                json.dumps(raw, ensure_ascii=False),
                datetime.now(UTC).isoformat(timespec="seconds"),
            ),
        )
        self.conn.commit()

    def key(
        self,
        eligible: EligibleSet,
        state: CustomerState,
        catalog: Catalog,
        rules: RuleSet,
        trigger: TriggerKind | None,
    ) -> str:
        return request_hash(self.model, user_prompt(eligible, state, catalog, rules, trigger))

    def chooser(self, trigger: TriggerKind | None) -> CachedAgentChooser:
        return CachedAgentChooser(self, trigger)

    def prefetch(
        self,
        states: list[CustomerState],
        eligible,
        catalog: Catalog,
        rules: RuleSet,
        trigger: TriggerKind,
    ) -> None:
        """Ask the agent, concurrently, for every state whose request isn't cached and that the agent would be
        asked about. A failed call is left for the Decision itself, which retries it and falls back."""
        todo: dict[str, tuple[EligibleSet, CustomerState]] = {}
        for state in states:
            es = eligible(state)
            if es.short_circuit is not None or es.send_window is None:
                continue
            key = self.key(es, state, catalog, rules, trigger)
            if key not in todo and self.get(key) is None:
                todo[key] = (es, state)
        if not todo:
            return

        def ask(item: tuple[EligibleSet, CustomerState]) -> dict[str, Any] | None:
            agent = AgentChooser(self.client, self.model, trigger)
            # Any answer, even a bad one, is cached; an error is retried by the Decision itself.
            with contextlib.suppress(Exception):
                agent(item[0], item[1], catalog, rules)
            return agent.last_output

        with ThreadPoolExecutor(PREFETCH_WORKERS) as pool:
            answers = list(pool.map(ask, todo.values()))
        self.calls += len(todo)
        for key, raw in zip(todo, answers, strict=True):
            if raw is not None:
                self.put(key, raw)


class CachedAgentChooser:
    """A chooser (`pipeline.ChooserFn`) that answers from the cache, else asks the agent and caches the answer.
    `last_output` is the agent's tool input, cached or fresh, for the Decision log."""

    def __init__(self, cache: AgentCache, trigger: TriggerKind | None):
        self.cache = cache
        self.trigger = trigger
        self.last_output: dict[str, Any] | None = None

    def __call__(
        self, eligible: EligibleSet, state: CustomerState, catalog: Catalog, rules: RuleSet
    ) -> Proposal:
        self.last_output = None
        agent = AgentChooser(self.cache.client, self.cache.model, self.trigger)
        if eligible.send_window is None:
            return agent(eligible, state, catalog, rules)
        key = self.cache.key(eligible, state, catalog, rules, self.trigger)
        raw = self.cache.get(key)
        if raw is not None:
            self.last_output = raw
            return to_proposal(raw, eligible)
        self.cache.calls += 1
        try:
            return agent(eligible, state, catalog, rules)
        finally:
            self.last_output = agent.last_output
            if agent.last_output is not None:
                self.cache.put(key, agent.last_output)
