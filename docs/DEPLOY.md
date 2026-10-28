# Deploying

The deployed app runs on one AWS Lightsail instance with Docker Compose. Compose runs two containers:

- `app` runs `offer-engine start`: the Offer Bot, the Customer Bots, the console (port 8501) and the live engine view
  (port 8502). The SQLite databases live in `~/offer-engine/data` on the instance, mounted into the container, so a
  redeploy keeps them.
- `tunnel` runs a Cloudflare Tunnel. It connects out to Cloudflare, which serves the app over HTTPS:

| URL | Serves |
|---|---|
| https://offers.uselattice.app | the live engine view |
| https://offers-console.uselattice.app | the console |

The instance opens no web port. The bots poll Telegram, so nothing needs to reach the instance except SSH.

Both pages are open, with no password. Anyone with the link can change Rules, advance the Simulation Clock or reset
the demo. To add a password, set `CONSOLE_PASSWORD` in the instance's `.env` and run `docker compose up -d`.

## Keep Lattice safe

`uselattice.app` also hosts Lattice. The tunnel adds two DNS records, `offers` and `offers-console`, and changes
nothing else. In Cloudflare, don't touch any other record or any zone-wide setting (SSL/TLS mode, WAF, rules, cache):
they apply to Lattice too.

Use one-level subdomains only. Cloudflare's free certificate covers `*.uselattice.app` but not
`*.offers.uselattice.app`, so `console.offers.uselattice.app` would fail HTTPS.

## One-time setup

`scripts/deploy-wizard.sh` walks steps 1–8 one screen at a time: it opens each dashboard, runs the commands and
checks each result. It builds the instance's `.env` on the laptop as `.env.poe` (gitignored) instead of editing it
with nano. Re-running it is safe, because every stage you already finished offers to skip.

### 1. Cap Claude spend

In the Anthropic console, set a monthly spend limit of $100 on the workspace that owns `ANTHROPIC_API_KEY`.

### 2. Create the instance

In Lightsail, create an instance: Linux, Ubuntu 24.04 LTS, the 2 GB RAM plan, region Mumbai (`ap-south-1`). Use
your own SSH key or download Lightsail's. On the instance's Networking tab, delete the HTTP (80) rule and keep only
SSH (22).

Add an alias on the laptop in `~/.ssh/config`, so the commands below can say `poe`:

```
Host poe
  HostName <instance public IP>
  User ubuntu
  IdentityFile ~/.ssh/<your key>
```

Install Docker on the instance, then log out and back in so the group change applies:

```bash
ssh poe 'curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker ubuntu'
```

### 3. Create the tunnel

In the Cloudflare dashboard, open Zero Trust › Networks › Tunnels › Create a tunnel › Cloudflared. Name it
`offer-engine`. The install command it shows ends in `--token <token>`: copy the token.

Add two public hostnames (routes) to the tunnel:

| Subdomain | Domain | Service |
|---|---|---|
| `offers` | `uselattice.app` | HTTP, `app:8502` |
| `offers-console` | `uselattice.app` | HTTP, `app:8501` |

`app` is the compose service name. The tunnel container reaches it over compose's network.

### 4. Copy the code

From the laptop, on the commit to deploy. This copies exactly the committed tree, so the instance needs no GitHub
access:

```bash
ssh poe 'mkdir -p offer-engine/data'
git archive HEAD | ssh poe 'tar -x -C offer-engine'
```

### 5. Write the instance's `.env`

Copy the laptop's `.env`, then edit it on the instance:

```bash
scp .env poe:offer-engine/.env
ssh poe 'chmod 600 offer-engine/.env && nano offer-engine/.env'
```

Set these on the instance:

```
TUNNEL_TOKEN=<token from step 3>
AGENT_MODE=replay
DEMO_SEED=7
CONSOLE_PASSWORD=
DB_PATH=
```

`DB_PATH` stays empty, so the app uses `data/offer_engine.db` inside the mounted folder.

### 6. Copy the databases

Stop `offer-engine start` on the laptop first. SQLite folds its `-wal` file into the database when the last
connection closes, so check that none is left, then copy both files:

```bash
ls data/*.db-wal                          # must print nothing
tar -czf /tmp/poe-data.tgz -C data offer_engine.db demo.db
scp /tmp/poe-data.tgz poe:
ssh poe 'tar -xzf poe-data.tgz -C offer-engine/data && rm poe-data.tgz'
```

The chat links copy over too: Telegram chat IDs are the same whichever machine runs the bots.

### 7. Start

Only one process may poll each bot token. The laptop's bots must stay stopped while the instance runs.

```bash
ssh poe 'cd offer-engine && docker compose up -d --build'
ssh poe 'cd offer-engine && docker compose logs -f'
```

The log shows lines prefixed `[offer-bot]`, `[customer-bots]`, `[console]` and `[live]`, and the tunnel's
`Registered tunnel connection` lines.

### 8. Check

From a phone, send `/start` to the Offer Bot: the Persona buttons arrive. Pick one, send `/offers`: an Offer Card
arrives. Open https://offers.uselattice.app, press Reset, run a scenario: its Decision plays back. Open
https://offers-console.uselattice.app: the Decision log loads.

## Day to day

| Task | Command |
|---|---|
| Redeploy after a commit | `git archive HEAD \| ssh poe 'tar -x -C offer-engine'` then `ssh poe 'cd offer-engine && docker compose up -d --build'` |
| Follow logs | `ssh poe 'cd offer-engine && docker compose logs -f app'` |
| Reset the demo | the live page's Reset button, or `ssh poe 'cd offer-engine && docker compose exec app uv run --no-sync offer-engine demo reset'` |
| Run any CLI command | `ssh poe 'cd offer-engine && docker compose exec app uv run --no-sync offer-engine <command>'` |
| Memory use | `ssh poe 'docker stats --no-stream'` |
| Stop | `ssh poe 'cd offer-engine && docker compose down'` |
| Run the bots on the laptop again | `ssh poe 'cd offer-engine && docker compose stop app'` first |
| Some requests get a Cloudflare 502 | `ssh poe 'docker ps'`: only `offer-engine-app-1` and `offer-engine-tunnel-1` may run. Any other `cloudflared` container shares the tunnel but can't resolve `app`; `docker rm -f` it |

A redeploy never touches `data/`. `tar -x` adds and overwrites files but leaves files deleted from the repo in
place. They do no harm.

## Cost

- Lightsail 2 GB: about $12 a month, paid from AWS credits.
- Claude: the demo scenarios replay recordings and cost nothing. Live calls come from Decisions for chat-attached
  Customers (Testers, Customer Bots) when evaluators use the bots or advance the clock. An Offer agent Decision on
  `claude-opus-5-5` ($4 / $20 per million tokens) sends about 2,300 input tokens and returns a few hundred output
  tokens with thinking: about $0.03. Customer Bot replies on `claude-haiku-5-5` cost under $0.001 each. Ten
  evaluators making 20 Decisions each is about $6 a day. The $100 cap covers about 3,000 agent Decisions.

## After judging

Delete the Lightsail instance. In Cloudflare, delete the `offer-engine` tunnel and the `offers` and
`offers-console` DNS records.
