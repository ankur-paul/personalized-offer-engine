# T29 — Deploy to an always-on host
**Status:** TODO
**Prereqs:** T24, T25 · **Branch:** t29-deploy

## Goal
The Offer Bot, Customer Bot simulator and console run on an always-on host in polling mode, so judges can use the
bot with the laptop off until judging ends. Mandatory (PLAN §7, §8 cut line; QnA Q7).

## Scope / files
- Pick the host (Railway, Fly.io or a free-tier VM) that gives a persistent volume for SQLite and runs one
  long-lived container. Record the choice and why in Details as `Done as built`.
- `Dockerfile` (or the host's equivalent): uv install, `offer-engine start` as the entry point; the DB on the
  persistent volume (`DB_PATH`).
- `docs/DEPLOY.md`: one-time setup (secrets from `.env` into the host's secret store, volume, first
  `generate --customers 10000`, `lift fit`, `chats link-showcase`), redeploy, logs, how to stop.
- Console exposed with `CONSOLE_PASSWORD` set (gate from T21).

## Details
- Never commit secrets; the host reads them from its secret store.
- Only one process may poll each bot token: stop the laptop instance before the host starts (say so in DEPLOY.md).
- Make the agent use `FAST_AGENT_MODEL` for Customer Bots and the configured `OFFER_AGENT_MODEL` for offers;
  estimate daily cost at expected demo traffic and note it in DEPLOY.md.
- This ticket needs the user's host account: when blocked on it, set
  `**Status:** BLOCKED (needs human: host account / payment)`.

## Tests
manual: see Check. Add `tests/test_dockerfile.py` only if cheap (e.g. the image builds in CI); otherwise none.

## Check
Laptop bot stopped; from a phone, `/start` the Offer Bot → Persona buttons arrive; `/offers` → Offer Card; the
console URL asks for the password and shows the Decision log.

## Done when
- [ ] Bots and console run on the host with a persistent database
- [ ] `docs/DEPLOY.md` lets someone else redeploy
- [ ] Bot works from a phone with the laptop off
- [ ] PROGRESS.md line added; FEATURES.md updated; `uv run pytest` green
- [ ] Committed: `T29: deploy to always-on host`
