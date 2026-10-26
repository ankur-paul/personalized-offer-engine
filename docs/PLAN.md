# Personalised Offer Engine: Plan

> Status: **v2, agreed** after a grilling session (2026-10-22). Vocabulary is defined in `GLOSSARY.md` and capitalised terms below use it. Hard-to-reverse decisions are in `docs/adr/`. Calibration sources: `docs/research/ecommerce-benchmarks.md`.

## 1. What we're building

A system that decides **which Offer, if any**, each Customer of a fictional Indian online marketplace should get, and **when**, and delivers it over Telegram. Marketing-written Rules set the limits; an agent (Claude) chooses and personalises within them; Validation checks every agent choice before it is sent.

The business idea everything hangs on: *a discount sent to someone who would have bought anyway is lost margin.* The engine targets **Lift** (who changes behaviour because of the Offer), picks the **cheapest Offer that captures most of it**, and is willing to send **No Offer**.

Constraints: solo build, ~1–2 weeks. Synthetic data only. Secrets in `.env`, never committed. Small commits. README + `CLAUDE.md`. Bot running until judging ends.

## 2. The world

### 2.1 Marketplace
- General Indian marketplace in ₹, 5–6 categories with very different margins (e.g. electronics ~8%, fashion ~45%) so margin-floor Rules visibly bite.
- Synthetic catalog with prices and margins.

### 2.2 Customers
- ~10k generated Customers: signup date, city tier, device, acquisition channel, loyalty tier, points balance and expiry.
- 6–12 months of event history: sessions, product views, add-to-cart, cart abandonment, orders, returns, points earned/burned, and **past Offers sent partly at random** (as A/B tests would be), with outcomes. Includes a festive spike.
- Realism targets (long-tailed spend, cart abandonment, recovery rates, coupon redemption, repeat rate, seasonality) are calibrated against `docs/research/ecommerce-benchmarks.md`, enforced by an automated check script.

### 2.3 Ground Truth (ADR 0002)
- Each Customer has, per Offer Type, a hidden response formula: base chance of buying in 7 days, max Lift (negative for Sleeping Dogs), and saturation. E.g. `p(d) = base + maxLift · (1 − e^(−d/k))`.
- Parameters are drawn from observable behaviour plus noise (frequent recent buyers → high base; heavy coupon users → high discount sensitivity; small baskets / tier-2–3 cities → high free-shipping sensitivity), so the engine can infer them imperfectly.
- Response Class (Persuadable, Sure Thing, Lost Cause, Sleeping Dog) is derived from the formulas, for reporting only.
- **The decision pipeline never reads Ground Truth.** Doing so is a bug.

### 2.4 Simulation Clock (ADR 0003)
One global clock for every Rule, event and expiry. Only the console advances it (manual +1 day, or an auto mode for demos). Wall-clock time is used only for Telegram delivery.

### 2.5 Live world
Each simulated day, the simulator generates events for all ~10k Customers, and Triggers and the Daily Sweep run the pipeline for every one of them. The agent decides for Customers attached to a Customer Bot or a Tester. The rule-based chooser that the Fallback uses decides for everyone else. Ground Truth settles outcomes: a plain weighted coin flip for Customers without a chat, the bounded role-play for Customer Bots (§4.2), and the flip after a Claim for Testers (§4.1). The offline Policy simulator (§5) reuses the same day-step code.

## 3. Deciding

### 3.1 Triggers
- Event triggers (core): cart abandoned, points expiring soon, long gap since last order, first order delivered.
- Daily Sweep: win-back and lapse across all Customers once per simulated day.
- On request: `/offers`.

All go through the same pipeline.

### 3.2 Offer Types (launch)
% off a category (with a ₹ cap) · flat ₹ off above a minimum basket · free shipping · points multiplier · **Nudge** (no incentive, zero cost) · plus **No Offer**. Cart recovery and points expiry are Triggers, not Offer Types. Bundles and tiered offers are out of scope.

### 3.3 Rules
Examples: max discount per segment and category; margin floor; frequency cap; cooldown after Redemption; weekly budget and per-Offer cost cap; eligibility; allowed send hours and max send delay; Holdout percentage; Fatigue Pause settings.

- **Strictest wins** when Rules conflict. Every Decision records its **Binding Rule**.
- **Opt-out is absolute**; nothing overrides it until the Customer starts again.
- **Fatigue Pause**: 3 "Not now" within 14 simulated days pauses Offers for 14 days.
- **Reserved Budget** at worst-case cost by default; console toggle to expected cost with a visible overspend warning.
- Rule changes are versioned. Offers already sent are honoured under the version they passed; new Rules apply to new Decisions. The console has an emergency "withdraw outstanding Offers".
- **Campaigns** (after the core works): named simulated date ranges that temporarily change named Rules, and may loosen them.

### 3.4 Estimating Lift
The engine learns Estimated Lift from the synthetic history's past random Offers. v1: per-segment averages. v2: a two-model uplift learner (with-Offer vs without-Offer classifiers). The agent sees Estimated Lift per eligible Offer, never Ground Truth.

### 3.5 Decision pipeline (ADR 0001)
1. **Rules** compute the Eligible Set (allowed Offer Types and parameter ranges) for this Customer now. Holdout and Opt-out short-circuit to No Offer.
2. **Agent** picks one Offer or No Offer from the Eligible Set, its parameters, the featured category and products (only from the Customer's own recent events/affinities), the send time (now or hour H within allowed hours), a caption, and a short reason.
3. **Validation** re-checks everything against every Rule, including the **Caption Check** (no numbers, amounts or deadlines that differ from the Offer, no promises not in the Offer, no invented urgency, length limit). On failure or agent outage, use the rule-based **Fallback**.
4. Log the Decision: chosen Offer, chooser (agent/Fallback), reason, Binding Rule, rule version, Validation result.

## 4. Delivering

### 4.1 Offer Bot
- Sends an **Offer Card** image whose terms (amount, minimum basket, category, expiry) are drawn by code from the validated Offer, plus the agent's caption and buttons **Claim / Not now / Stop** (ADR 0005).
- Accepts Claims by button or text (`/claim CODE`) so Customer Bots can claim.
- **Testers** (humans) `/start`, pick a Customer from Persona Card buttons or "Surprise me", and get their own copy of it. Same code path as Customer Bots. A Tester who picks the Holdout Customer is told they're in the control group.
- A Tester's Claim becomes a Redemption by a weighted coin flip on that Customer's Ground Truth, with no agent nudge. The Offer Bot then tells the Tester the result, e.g. "Simulated order: ₹1,240 basket, code used".

### 4.2 Customer Bots (ADR 0004)
- 6–8 showcase Customers from the population, each embodied by a Customer Bot via Bot API 10.0 bot-to-bot messaging (Bot-to-Bot Communication Mode on for every bot). Cases: at-risk high value, new one-order, deal hunter, expiring points, cart abandoner, a Sure Thing who should get No Offer, and one deliberately in the Holdout.
- **Bounded role-play**: Ground Truth sets the base chance; an agent rates the message's fit to the Persona Card and nudges the chance by at most ±30%; a weighted coin flip decides Claim and Redemption; the agent writes a matching reply.
- Persona Cards are generated from Customer data by an agent, reviewed, then frozen. They never reveal Ground Truth.
- Later: haggling ("can you do 20%?") answered by the offer agent within Rules.

### 4.3 Claim vs Redemption
Claim = Customer took the code (interest only). Redemption = simulated purchase using it before expiry, with basket, order value and margin. Separate metrics.

### 4.4 Holdout
Permanent, hash-based on Customer ID, 10% by default (a Rule setting).

## 5. Measuring

- **Offline Policy comparison**: No Offers, Blanket 20%, Rules Only (all ~10k Customers) and Rules + Agent (stratified ~500 sample, fastest Claude model, cached).
- **Headline metric**: Incremental Margin per ₹ of offer spend, by Policy.
- Supporting: live funnel (sent → Claimed → Redeemed) vs Holdout; spend wasted on Sure Things; Validation rejections and Fallbacks; lift-by-decile (Estimated Lift graded against Ground Truth).

## 6. Marketing console (Streamlit)
- Rule forms with plain-English labels ("Never discount below __% margin"), version history with who/when and one-click revert.
- **Preview impact**: dry-run a rule change on the population before saving ("+1,240 Offers, +₹38k cost").
- Simulation Clock controls, Decision log with reasons and Binding Rules, results dashboard, emergency withdraw.

## 7. Engineering

- Python 3 + uv, python-telegram-bot, SQLite, Anthropic SDK, Streamlit. Look up current Claude model IDs and pricing when implementing; don't hard-code from memory.
- Three long-running processes sharing SQLite: **Offer Bot** (delivery, Claims, Triggers, pipeline), **Customer Bot simulator** (all Customer Bot tokens), **console**. Plus scripts for data generation, calibration check, offline simulation. One start command.
- `.env` (gitignored) and `.env.example`. An interactive setup script walks through creating bots in BotFather, enabling Bot-to-Bot Communication Mode, and filling `.env`.
- Rules engine and Validation are **pure functions built test-first**, including a property test ("random proposals that break any Rule never pass") and an adversarial set (bad captions, manipulative replies). Bot and console tested by hand.
- Hosting: laptop during development; always-on host (Railway/Fly/free-tier VM) in polling mode for judging.

## 8. Milestones

Each milestone is a working vertical slice, committed.

| # | Days | Milestone | Proves |
|---|---|---|---|
| M1 | 1 | Repo skeleton (uv, `.env.example`, `CLAUDE.md`, setup script). Offer Bot sends one hard-coded Offer Card to one Customer Bot (bot-to-bot proven) and to a Tester | Riskiest plumbing works on day 1 |
| M2 | 2–3 | Small generator (catalog with margins, ~200 Customers, events), Simulation Clock, Rules engine + Validation test-first, cart-abandoned Trigger → rule-based Offer | Offers stay within Rules |
| M3 | 4–5 | Agent chooses from Eligible Set and writes caption; Caption Check; Fallback; Decision log with Binding Rule | Every agent choice is checked |
| M4 | 5–7 | Full ~10k generator, Ground Truth, calibration check, history with random past Offers, Estimated Lift v1 | Data realism |
| M5 | 7–9 | Console (rule forms, versions, clock), Customer Bots with bounded role-play, Claims/Redemptions, Holdout, Persona Cards | Usability, live demo |
| M6 | 9–11 | Offline Policy simulator, results dashboard, preview impact | Relevance, readable results |
| M7 | 11+ | Adversarial set, Campaigns, uplift v2, send-time choice, haggling, deploy to host, README polish | Advanced functionality, submission |

**Cut line**: M1–M6 is the submission. M7 items drop one by one if time runs short, except deployment and README, which are mandatory.

**Contingency**: if M1 shows bot-to-bot messaging doesn't work as documented, switch to Testers only (own and friends' accounts) and show Customer Bots as a console view.

## Assumed (approved 2026-10-22)

Defaults chosen when the plan was split into tickets (`tickets/`). Several tickets rely on each of them.

### Code layout
- The package is `src/offer_engine/`, the console is `console/` (a Streamlit multipage app, one file per page in `console/pages/`), and tests live in `tests/`. Run everything with `uv run`.
- `offer-engine` is the CLI. `cli.py` discovers subcommands in `offer_engine/commands/`; each module there defines `register(subparsers)`. Adding a command never edits a shared file.
- `offer_engine/domain.py` holds the shared types (T02). Only a ticket whose Scope says so changes them.
- SQLite schema lives in `offer_engine/schema/`, one file per ticket named `tNN_<name>.sql`. Files apply in name order. A ticket adds its own file and doesn't edit another ticket's.
- `offer_engine/sim/` is the simulator. It is the only package that reads Ground Truth and the other hidden simulator data, all kept in tables named `sim_*` (`sim_ground_truth`, `sim_customer_traits`, …). The pipeline modules (`customers`, `budget`, `rules`, `validation`, `caption_check`, `pipeline`, `choosers`, `lift`, `triggers`, `daily_sweep`, `offer_bot`) never import `offer_engine.sim` and never name a `sim_*` table. A test from T02 enforces both. Entry points (`commands`, `console`, `customer_sim`) may import both sides.

### World and time
- The Simulation Clock counts in simulated hours. "+1 day" processes 24 hours in order. The Daily Sweep runs at 10:00 simulated time. Generated history ends at the clock's start time.
- An Offer is valid for 3 simulated days (Rule setting `offer_validity_days`). Codes look like `POE-` plus 6 uppercase letters and digits.
- Delivery goes through the database. The pipeline writes Offers as `queued` with a `send_at`. The Offer Bot polls for queued Offers to chat-attached Customers whose `send_at` has passed in simulated time. The day-step marks Offers to everyone else as sent. Other bot messages (Redemption notices, withdrawals) go through an `outbox` table.
- A Customer is chat-attached when the `chats` table links it to a Customer Bot or a Tester.

### Deciding
- Choosers are recorded on the Decision as `agent` (the agent's proposal passed Validation), `fallback` (the agent failed or was down, so the rules chooser decided) or `rules` (a Customer without a chat).
- The rules chooser serves as the Fallback, the chooser for Customers without a chat, and the Rules Only Policy. It picks the option and parameters that maximise Estimated Lift × expected margin − expected cost, and picks No Offer if nothing is positive. Until Estimated Lift exists (T16) it uses fixed priors per Offer Type from `offer_engine/choosers/priors.py`.
- Cost model: % off costs pct × expected basket in that category, capped at the ₹ cap (the cap is the worst case). Flat ₹ off costs the amount. Free shipping costs ₹40. A points multiplier costs the extra points × ₹0.25. A Nudge costs ₹0. Expected cost is the cost × the chance of Redemption.
- Estimated Lift v1 segments are loyalty tier × recency bucket (≤30, 31–90, >90 days since last order) × coupon-user flag, per Offer Type. A segment with fewer than 30 past Offers falls back to the Offer Type average.
- The Daily Sweep decides chat-attached Customers first, so the weekly budget can't run out before the live demo Customers are considered.
- Rule versions record "who" as a free-text name typed on the console form. There is no login.
- Agent model IDs come from `.env` (`OFFER_AGENT_MODEL`, `FAST_AGENT_MODEL`). Look them up with the `claude-api` skill when building T11.

### Outcomes and measuring
- A Customer without a chat buys within the Offer window with Ground Truth chance p(d). Every Redeemer counts as Claimed, and 25% of non-Redeemers Claim without buying.
- A Tester copy has the ID `<customer id>-t<telegram user id>` and the original's Holdout status. Copies are left out of population metrics.
- Blanket 20% sends 20% off the Customer's top category, uncapped, at every Trigger, to every Customer who isn't in the Holdout or opted out.
- An offline Policy run covers 28 simulated days after the history ends, with the same seed for every Policy.
- The adversarial set from M7 is split: bad captions ship with the Caption Check (T08), manipulative customer replies with haggling (T34).
- If T04 shows bot-to-bot messaging doesn't work, T04 goes BLOCKED and the §8 contingency applies: Customer Bots become a console view.

## Assumed (approved 2026-10-26): the demo

The demo pass (T35–T40) makes the demo repeatable and shows each Decision as it happens. The decisions behind it are in `docs/QnA.md` Round 12 (Q44–Q51):
- a separate live engine page;
- recorded agent answers replayed, with a switch to call Claude live;
- the 10k seed-7 world restored from a snapshot;
- ten named scenarios in four groups;
- outcomes shown as a chance with a seeded flip;
- a Ground Truth panel marked "hidden from the engine";
- the demo driven from scenario buttons, plus one Tester exchange on a phone.

### Code layout
- `offer_engine/demo/` holds the snapshot, agent replay and scenarios. `offer_engine/live/` holds the live engine page. Both are entry points like `commands`, `console` and `customer_sim`, so they may import both sides of the Ground Truth boundary. The boundary test doesn't change.
- The live page is FastAPI with Server-Sent Events and plain HTML, SVG and JS, with no build step. It runs on port 8502 as a fourth process in `offer-engine start`. When `CONSOLE_PASSWORD` is set, it asks for the same password with HTTP basic auth.

### Decision trace
- Each live Decision stores a stage-by-stage trace as JSON in `decision_traces`. The stages are the Trigger, the Customer's observable summary, each check that can stop an Offer, the Eligible Set with Binding Rules and Estimated Lift, the rules chooser's value per option, the agent's input and answer, each Validation check, any Fallback, and the Offer.
- The pipeline passes each stage to an optional listener as it finishes, so the live page can animate it.
- `offer-engine simulate` and Preview impact store no traces. If tracing slows the Daily Sweep on 10k Customers by more than 15%, only chat-attached Customers and scenario runs get a full trace.
- A trace never holds Ground Truth. The truth panel reads it through `offer_engine/sim/explain.py`.
- `validate` also returns the names of the checks it ran. Its failures don't change.

### Snapshot and agent replay
- `data/demo.db` (gitignored) is the 10k seed-7 world after `generate`, `lift fit` and `chats link-showcase`, at its starting simulated time. `offer-engine demo reset` copies it into `DB_PATH` with SQLite's backup API, so running bots keep their connections.
- `AGENT_MODE` is `live` (the default), `replay` or `record`. It covers the offer agent and the Customer Bot's fit rating.
- Recordings live in the committed `demo/agent_recordings.jsonl`. Each is keyed by a hash of the model, system prompt, tools and messages.
- When a replay has no recording, it calls Claude and records the answer if `ANTHROPIC_API_KEY` is set. Otherwise it raises: the offer agent falls back to the rules chooser, and the Customer Bot flips on Ground Truth alone.
- When `DEMO_SEED` is set, Offer codes come from the seed, the Customer and the Decision time instead of `secrets`.

### Scenarios
- A scenario has a name, a title, the point it proves, its Customer, setup steps, a Trigger, the expected Decision (Offer Type or No Offer, chooser, Binding Rule, Validation result) and an outcome seed. The scenarios live in `offer_engine/demo/scenarios.py`.
- A scenario runs on the demo database at the snapshot's simulated time, on its own Customer. A scenario that changes the Rules restores them before it ends. Any order of scenarios gives the same results.
- Customers come from the frozen Persona Cards where one fits. Otherwise the scenario names a Customer found in the seed-7 world. A scenario uses a Customer the engine actually treats as it claims; nothing is forced. C01377 gets 6% off fashion from the rules chooser but a Nudge from the agent, so `real-discount` uses C01588, a Persuadable with no chat (QnA Q52).
- The outcome chance is Ground Truth's 7-day chance for the Offer, nudged by the recorded message fit by at most ±30%. The flip is seeded by the scenario name and `SEED`. A scenario settles its own Offer, so scenario Offers never reach Telegram.
- `offer-engine demo check` runs every scenario on a fresh copy of the snapshot and prints PASS or FAIL for each.
