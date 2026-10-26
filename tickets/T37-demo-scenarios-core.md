# T37 — Demo scenarios: runner, saving margin, hard limits
**Status:** IN PROGRESS
**Prereqs:** T35, T36 · **Branch:** t37-demo-scenarios

## Goal
Named demo scenarios with known outcomes. You run each one from the CLI before the judges, and the live page
(T39) runs them from buttons. Each scenario prints its stage trace, its Decision and a seeded outcome, the same on
every run. `demo check` is the pre-demo test. This ticket builds the runner and the first six scenarios. Part 2 of
the demo pass: T35 / T36 → T37 → T38 / T39 → T40 (PLAN "Assumed (approved 2026-10-26) › Scenarios", QnA Q48, Q49).

## Scope / files
- `src/offer_engine/demo/scenarios.py`:
  - `Scenario(name, title, proves, customer_id, setup: Callable[[Connection, datetime], None] | None, trigger,
    expect: Expect, group)`.
  - `Expect(offer_type: OfferType | None, chooser: Chooser | None = None, binding_rule: str | None = None,
    validation_ok: bool | None = None)`.
  - `SCENARIOS: list[Scenario]` in demo order. T38 appends its scenarios at the end of this list.
- `src/offer_engine/demo/runner.py`:
  - `run(conn, name, *, on_stage=None, seed=None) -> ScenarioResult`. It runs the setup, fires the Trigger
    through `pipeline.decide(..., on_stage=...)` at the clock's current time, then settles the Offer, if any.
  - Settling: mark the Offer `sent`. A Customer with a Customer Bot chat goes through `roleplay.react`; any other
    Customer goes through `outcomes.draw_fate`. Both use `np.random.default_rng([SEED, zlib.crc32(name)])`.
    Then apply the Claim or "Not now" with `offer_bot.responses`.
  - `ScenarioResult` holds the Decision, the trace, `p_base`, `fit`, `p_used`, `buys`, `claims`, the reply text
    and `passed` (whether the Decision matches `expect`).
  - `check(snapshot_path) -> list[ScenarioResult]` runs every scenario, each on its own fresh copy of the snapshot
    (`offline.copy_db`), in a temp directory.
- `src/offer_engine/demo/output.py`: one formatter used by the CLI, and later by the live page's plain-text
  fallback.
- `src/offer_engine/commands/demo.py` (from T36): add `demo list`, `demo run <name>` and `demo check`.
  `demo check` prints `PASS`/`FAIL` per scenario and exits 1 on any FAIL.
- The six scenarios. Find each Customer on the seed-7 world and write it into the scenario:
  - `sure-thing`, "A Sure Thing gets No Offer": C02030 (Persona Card `sure_thing`).
  - `lost-cause-nudge`, "A Lost Cause gets a ₹0 Nudge, not a discount": C09823.
  - `real-discount`, "A Customer a discount moves gets one": a Customer the engine gives a % off or flat ₹ off.
    C01377 got 6% off fashion from the rules chooser on 2026-10-26.
  - `holdout`, "A Holdout Customer gets nothing": C04770 (Persona Card `holdout`).
  - `opted-out`, "Opt-out is absolute": a chat-attached Customer whose setup sends `/stop` first.
  - `fatigue-pause`, "Three Not nows pause Offers": the setup records three dismissed Offers in the last 14
    simulated days.
- `demo/agent_recordings.jsonl`: run `AGENT_MODE=record offer-engine demo check` once and commit the recordings.

## Details
- The scenarios run at the snapshot's simulated time (2026-12-01 00:00 on the seed-7 world) without advancing
  the clock. A scenario whose setup changes the Rules or a Customer restores them before it returns, so running
  `demo run a`, then `demo run b`, gives the same result as either alone.
- The agent decides for chat-attached Customers, so scenario expectations must hold under replay. Where the
  agent and the rules chooser could disagree, `Expect` leaves `chooser` unset and names only what matters to the
  point (e.g. "not a discount").
- Scenario Offers are settled by the runner, so the Offer Bot never sends them to Telegram.

## Tests
- `tests/demo/test_scenarios.py` on the 300-Customer fixture, with a fake agent and fixture-specific stand-in
  scenarios:
  - The runner calls `on_stage` per stage.
  - The same seed gives the same outcome twice.
  - Setup and restore leave the Rules and other Customers unchanged.
  - Running two scenarios in either order gives the same results.
- `tests/demo/test_scenarios_world.py`, marked `demo`: skips unless `data/demo.db` exists. It runs `check()` with
  `AGENT_MODE=replay` and asserts every scenario passes. Register the `demo` marker in `pyproject.toml`.

## Check
```
uv run offer-engine demo reset
AGENT_MODE=replay uv run offer-engine demo list
AGENT_MODE=replay uv run offer-engine demo run sure-thing
AGENT_MODE=replay uv run offer-engine demo check       # twice: identical output, 6 PASS
```

## Done when
- [ ] `demo list`, `demo run <name>` and `demo check` work, with six scenarios
- [ ] Each scenario prints its trace, Decision and seeded outcome; repeated runs match
- [ ] Recordings committed; `demo check` passes with no API key under replay
- [ ] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [ ] Committed: `T37: demo scenarios runner, saving margin and hard limits`
