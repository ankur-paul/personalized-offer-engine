# `make` runs the whole project: installs dependencies, checks .env, builds the world on first run, then starts
# the Offer Bot, the Customer Bots and the console (http://localhost:8501). Ctrl-C stops all three.

# The frozen Persona Cards in personas/ belong to the 10k seed-7 world. Override DB if .env sets DB_PATH.
DB ?= data/offer_engine.db
CUSTOMERS ?= 10000
SEED ?= 7

RUN := uv run offer-engine

# A failed build removes the half-built database, so the next run starts over.
.DELETE_ON_ERROR:

.PHONY: run install env world reset demo-snapshot demo-reset console test help

run: install env world ## Install, check .env, build the world if missing, start everything
	$(RUN) start

install: ## Install dependencies into .venv
	uv sync

env: ## Check that .env has every required key (fill it with `uv run offer-engine setup`)
	@$(RUN) check-env || { echo "Missing .env keys: copy .env.example to .env or run 'uv run offer-engine setup'."; exit 1; }

world: $(DB) ## Build the world unless the database exists

# generate deletes chat links, so the Customer Bots are linked after it.
$(DB):
	$(RUN) generate --customers $(CUSTOMERS) --seed $(SEED)
	$(RUN) lift fit
	$(RUN) chats link-showcase

reset: ## Delete the database and build a fresh world
	rm -f $(DB) $(DB)-journal $(DB)-wal $(DB)-shm
	$(MAKE) world

demo-snapshot: ## Save the database as the demo snapshot (data/demo.db)
	$(RUN) demo snapshot

demo-reset: ## Copy the demo snapshot back into the database; running bots keep working
	$(RUN) demo reset

console: install world ## Run only the console
	uv run streamlit run console/app.py

test: install ## Run the test suite
	uv run pytest

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'
