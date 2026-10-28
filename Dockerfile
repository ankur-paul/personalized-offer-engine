# The whole app in one image: `offer-engine start` runs the Offer Bot, the Customer Bots, the console (8501) and
# the live engine view (8502). The database lives in /app/data, a volume, so redeploys keep it (docs/DEPLOY.md).
FROM ghcr.io/astral-sh/uv:0.12.6-python3.12-trixie-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1 PYTHONUNBUFFERED=1

# Dependencies first, so a code change doesn't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project

COPY . .
RUN uv sync --locked

EXPOSE 8501 8502
CMD ["uv", "run", "--no-sync", "offer-engine", "start"]
