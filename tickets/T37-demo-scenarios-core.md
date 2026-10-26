# T37 — Demo scenarios: runner, saving margin, hard limits
**Status:** DONE
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

- Done as built:
  - **`real-discount` uses C01588**, a Persuadable with no chat: 7% off fashion from the rules chooser, Binding Rule
    `max_pct_by_loyalty_tier`. C01377 has a Customer Bot chat, so the agent decides for her, and Claude gave her a
    free Nudge on her grocery cart. The user chose C01588 (QnA Q52). Its outcome is the plain Ground Truth draw, with
    no Customer Bot fit or reply.
  - **Customers.** `opted-out` uses C09918 (Persona Card `new_one_order`, a Nudge when opted in). `fatigue-pause` uses
    C00005, with no chat (free shipping when not paused), which leaves C01835 and C04310 free for T38. Sure Thing and
    Lost Cause both got the agent's own No Offer and Nudge, matching the rules chooser.
  - **Restore.** `Scenario` has an extra `restore` step beside `setup`. The setups are factories that take the
    Customer (`stop`, `restart`, `three_not_nows`, `forget_not_nows`), so the tests reuse them on fixture Customers.
  - **Reruns.** `run` first clears what an earlier run wrote for the scenario's Customer at or after the clock's time
    (Decisions, traces, Offers, fates, events, `trigger_log`). Without it a second click hits the frequency cap or
    gets a new Offer code. A rerun of `demo run lost-cause-nudge` printed the same code, fit and replies.
  - **Seeded codes.** The Offer code is on the Offer Card, so the Customer Bot's recorded answer replays only if the
    code repeats. `pipeline.seeded_codes(seed)` (a context manager next to `new_code`) seeds codes the way
    `DEMO_SEED` does, and the runner uses it with the outcome seed. This is the only pipeline change.
  - **Cart-abandoned Trigger.** The runner records the abandoned cart first, as `offer-engine trigger cart-abandoned`
    does, using its `abandoned_product`.
  - **Output.** `ScenarioResult` also holds the `scenario`, the Offer Bot's `bot_reply` and the `mismatches` behind a
    FAIL. `decisions explain`'s stage printing moved into `commands.decisions.stage_lines`, which `demo/output.py`
    reuses. `demo check` prints one line per scenario with no timings, so two runs print the same.
  - **Tests** use the 50-Customer `world` fixture; there is no 300-Customer one. `demo check` takes about 30 s on the
    10k snapshot (one 593 MB copy per scenario). `tests/demo/test_scenarios_world.py` runs in the default suite
    whenever `data/demo.db` exists, with the key unset and the role-play client replay-only.
  - **Recordings.** `AGENT_MODE=record offer-engine demo check` made five recordings; the two for C01377 were dropped
    after the switch to C01588, leaving three (two offer-agent answers, one Customer Bot fit). The Check ran with the
    key commented out of `.env`: 6 PASS twice, identical output, no new recordings.

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
- [x] `demo list`, `demo run <name>` and `demo check` work, with six scenarios
- [x] Each scenario prints its trace, Decision and seeded outcome; repeated runs match
- [x] Recordings committed; `demo check` passes with no API key under replay
- [x] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [x] Committed: `T37: demo scenarios runner, saving margin and hard limits`
