# Personalised Offer Engine

The engine decides which offer, if any, each Customer of a fictional Indian online marketplace gets, and when. It
sends each offer over Telegram. A discount sent to someone who would have bought anyway is lost margin, so the
engine optimises Incremental Margin instead of the chance to buy. It sends No Offer when no offer pays for itself.

All data is synthetic. Capitalised terms such as Offer, Rule and Lift are defined in [GLOSSARY.md](GLOSSARY.md).

## How a Decision is made

Every Trigger runs the same pipeline. A Trigger is an abandoned cart, points about to expire, 45 days without an
order, a first delivery, the Daily Sweep at 10:00, or a Tester's `/offers`.

1. The Rules compute the Eligible Set: the Offer Types this Customer may get now, with their parameter ranges.
   Holdout and opt-out end the pipeline with No Offer ([ADR 0001](docs/adr/0001-rules-before-agent.md)).
2. The Claude agent picks one Offer or No Offer from the Eligible Set, sets its parameters and writes the caption.
3. Validation re-checks the proposal against every Rule. The Caption Check rejects numbers, amounts and deadlines
   that differ from the Offer's terms. If Validation fails or the agent is down, the rule-based Fallback decides.
4. Code draws the Offer Card from the validated terms. The agent writes only the caption
   ([ADR 0005](docs/adr/0005-agent-writes-caption-not-terms.md)).

Each Customer has a hidden Ground Truth: a buying chance per Offer Type. Only the simulator reads it. The pipeline
sees observable behaviour and the Estimated Lift learned from past Offers
([ADR 0002](docs/adr/0002-hidden-ground-truth.md)). Rules, events and expiries run on a Simulation Clock that you
advance from the console ([ADR 0003](docs/adr/0003-simulation-clock.md)).

## Run it

You need Python 3.12 or later, [uv](https://docs.astral.sh/uv/), a Telegram account and an Anthropic API key.

1. Create the bots and fill `.env`:

   ```bash
   uv run offer-engine setup
   ```

   The wizard walks you through BotFather for the Offer Bot and 6 to 8 Customer Bots, then asks for the API key
   and the model IDs. [.env.example](.env.example) lists every key.

2. Build the world and start everything:

   ```bash
   make
   ```

   On the first run, `make` generates 10,000 Customers with 12 months of history (about 80 seconds), fits
   Estimated Lift and links the Customer Bots to the showcase Customers. Later runs keep the database.

`make` runs four processes on one SQLite database:

| Process | What it does |
|---|---|
| Offer Bot | Sends Offer Cards, handles Claims, `/start` and `/offers` |
| Customer Bots | Each bot plays one showcase Customer and replies in character ([ADR 0004](docs/adr/0004-bounded-roleplay-customer-bots.md)) |
| Marketing console | http://localhost:8501: Simulation Clock, Decisions, Rules and Results pages |
| Live engine view | http://localhost:8502: each Decision as it happens, stage by stage |

`make reset` deletes the database and builds a new world. `make help` lists every target.

## Try it

- **On Telegram:** send `/start` to the Offer Bot, pick a Customer to play, then send `/offers`. If you claim the
  Offer and your Customer would buy, the bot replies with a simulated order.
- **In the console:** press **+1 day** on the Simulation Clock page. Triggers fire, the Daily Sweep runs and the
  Customer Bots answer their Offers. The Rules page changes the limits; every change saves a new rule version.
- **Demo scenarios:** before you advance the clock, run `make demo-snapshot` once in a second terminal. Then press
  a scenario button in the live engine view. Each scenario proves one point, such as "A Sure Thing gets No Offer" or "Validation rejects a rule-breaking proposal".
  `uv run offer-engine demo list` prints them all.

Set `AGENT_MODE=replay` in `.env` to play recorded Claude answers from `demo/agent_recordings.jsonl` instead of
calling the API.

## Results

`offer-engine simulate` runs each Policy for 28 simulated days on its own copy of the database, from the same start
and seed. This run used the 10k seed-7 world, scored on a stratified 500-Customer sample against No Offers:

| Policy | Incremental Margin per ₹ of offer spend |
|---|---|
| Blanket 20% off | −0.08 |
| Rules Only | +28.93 |
| Rules + Agent | +22.60 |

A blanket discount loses money. Rules Only added ₹20,887 of margin and Rules + Agent ₹13,052. Rules Only's figure
per ₹ is high partly because most of its Offers are ₹0 Nudges, which add margin at no spend. Rules + Agent scored
below Rules Only on this seed, and one seed can't tell whether that gap is real. The full run takes about 100 minutes. For a short run:

```bash
uv run offer-engine simulate --policies rules_only --days 3
```

The console's Results page charts the latest run.

## Tests

```bash
uv run pytest            # runs in parallel on every core
uv run pytest -m live    # talks to Telegram or the Claude API
uv run pytest -m slow    # timing tests; run them alone
```

The Rules engine and Validation are pure functions, built test-first. A property test checks that random
rule-breaking proposals never pass Validation.

## Limits

[FEATURES.md](FEATURES.md) describes what the app does now and lists its known limits. The main ones:

- The agent decides only for Customers linked to a chat. The rules chooser decides for the rest.
- Past Offers redeem at about 15% of sends, above the 1.5 to 5% that the calibration targets allow
  ([docs/QnA.md](docs/QnA.md) Q41).
- Results come from one seed.

## Docs

| File | What it holds |
|---|---|
| [docs/PLAN.md](docs/PLAN.md) | The agreed plan |
| [docs/adr/](docs/adr/) | Decisions that change only through a new ADR |
| [GLOSSARY.md](GLOSSARY.md) | Every domain term |
| [FEATURES.md](FEATURES.md) | What the app does now, and its known limits |
| [PROGRESS.md](PROGRESS.md) | What was built, in order, and known issues |
| [docs/QnA.md](docs/QnA.md) | Questions and answers from the planning sessions |
| [docs/research/ecommerce-benchmarks.md](docs/research/ecommerce-benchmarks.md) | Sources for the calibration targets |
| [tickets/](tickets/) | The work, one ticket per feature |

## Secrets

`.env` holds the bot tokens and the API key. Git ignores it. `offer-engine check-env` shows which keys are set,
never their values.
