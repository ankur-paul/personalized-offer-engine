# T36 — Demo snapshot and agent replay
**Status:** DONE
**Prereqs:** — · **Branch:** t36-demo-snapshot-replay

## Goal
The demo starts from the same world every time, and the agent gives the same answers every time. `demo reset`
brings back the 10k seed-7 world in seconds, and replay mode plays recorded Claude answers back. Part 1 of the
demo pass: T35 / T36 → T37 → T38 / T39 → T40 (PLAN "Assumed (approved 2026-10-26)", QnA Q45, Q46).

## Scope / files
- `src/offer_engine/demo/__init__.py` and `src/offer_engine/demo/snapshot.py`:
  - `snapshot(conn, path=Path("data/demo.db"))` copies the current database to `path` with
    `sqlite3.Connection.backup`.
  - `reset(conn, path=Path("data/demo.db"))` copies `path` back into the open database with the backup API, so
    other processes keep their connections. It raises `FileNotFoundError` with a hint to run `demo snapshot` if
    `path` is missing.
- `src/offer_engine/demo/replay.py`:
  - `ReplayClient(real: Any | None, mode: str, path: Path = Path("demo/agent_recordings.jsonl"))`, exposing
    `.messages.create(**kwargs)` like the Anthropic client.
  - The key is the SHA-256 of the canonical JSON of `model`, `system`, `tools` and `messages`.
  - `live` calls `real` and doesn't record. `record` calls `real` and appends `{key, model, request, response}`
    to the file. `replay` returns the recorded response.
  - A replay with no recording calls `real` and records the answer when `real` is set. Otherwise it raises
    `ReplayMiss`.
  - Responses are stored as plain JSON (`stop_reason`, and `content` blocks with `type`, `name`, `input`, `text`)
    and turned back into objects with those attributes, so `agent_chooser._tool_input` and `roleplay.rate_fit`
    work unchanged.
- `src/offer_engine/config.py`: settings `agent_mode` (env `AGENT_MODE`: `live` | `replay` | `record`, default
  `live`) and `demo_seed` (env `DEMO_SEED`, int, optional). Add both to `ENV_KEYS` and `.env.example`.
- `src/offer_engine/pipeline.py`: `_client` wraps the Anthropic client in `ReplayClient` by `agent_mode`, and
  `new_code` derives the code from `DEMO_SEED`, the Customer and the Decision time when `DEMO_SEED` is set. Change
  only these two functions: T35 edits `_decide` and `_write` in parallel.
- `src/offer_engine/customer_sim/app.py`: `agent_client` wraps its client the same way.
- `src/offer_engine/commands/demo.py`: `offer-engine demo snapshot` and `offer-engine demo reset`. Print the
  simulated time and Customer count after each. T37 adds more subcommands to this file.
- `Makefile`: `demo-reset` (runs `demo reset`) and `demo-snapshot`. Add both to `.PHONY` and `make help`.
- `demo/agent_recordings.jsonl`: committed and empty in this ticket. T37 fills it.

## Details
- Recordings hold synthetic data only: no secrets, no `.env` values.
- Copying a 600 MB database with the backup API should take a few seconds. Record the time as `Done as built`.
- A replay with no recording, in the offer agent, falls back to the rules chooser through the pipeline's
  existing error path. In a Customer Bot, the bot flips on Ground Truth alone, as it does today when the agent
  fails.
- `offline.agent_client` (T26) keeps its own `sim_agent_cache`. Don't change it.
- Done as built: `pipeline.default_chooser` changed too. In `replay` mode it picks the agent with no API key, else
  the Check's last command would get the rules chooser. `_insert_offer` passes the Customer, the Decision time and
  an attempt number to `new_code`, so a taken seeded code moves to the next attempt instead of looping.
- Done as built: the snapshot is written in rollback-journal mode, one file with no `-wal` beside it. On the
  593 MB 10k world, `demo snapshot` took 4.5–6.8 s and `demo reset` 12.4 s.
- Done as built: `tests/test_demo_snapshot.py` uses the 50-Customer `world` fixture; there is no 300-Customer one.
- Done as built: `ANTHROPIC_API_KEY=` on the command line doesn't unset the key (`read_env` falls back to `.env`
  for an empty variable), so the Check ran with the key emptied in `.env`. Same code `POE-G1H2WD`, caption and
  reason as the recorded run.

## Tests
- `tests/test_replay.py`, with a fake client counting calls:
  - In `record` mode, the call goes through and is written down.
  - In `replay` mode, the same request returns the same answer with no call.
  - A different prompt misses: with a client it calls through and records, without one it raises `ReplayMiss`.
  - The agent chooser and `rate_fit` accept a replayed response.
- `tests/test_demo_snapshot.py`: on the 300-Customer fixture, take a snapshot, change the database (a Decision, a
  clock advance), reset, and the database matches the snapshot. A second open connection still works after the
  reset.
- `tests/test_pipeline.py`: with `DEMO_SEED` set, the same Decision twice gets the same Offer code.
- `tests/test_makefile.py`: `demo-reset` and `demo-snapshot` appear in `make help`.

## Check
```
uv run offer-engine demo snapshot
AGENT_MODE=record DEMO_SEED=7 uv run offer-engine trigger cart-abandoned C09823   # one real Claude call
uv run offer-engine demo reset
AGENT_MODE=replay DEMO_SEED=7 ANTHROPIC_API_KEY= uv run offer-engine trigger cart-abandoned C09823
```
The last command prints the same Offer code, caption and reason as the recorded run, with no API key set.

## Done when
- [x] `demo snapshot` and `demo reset` work, and reset doesn't break other open connections
- [x] `AGENT_MODE=replay` plays recorded answers with no API call, for the offer agent and Customer Bots
- [x] `DEMO_SEED` makes Offer codes repeatable
- [x] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [x] Committed: `T36: demo snapshot and agent replay`
