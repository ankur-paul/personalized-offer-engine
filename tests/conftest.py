import pytest

from offer_engine.config import ENV_KEYS

OPT_IN_MARKERS = ("live", "slow")


def pytest_collection_modifyitems(config, items):
    """Skip `live` and `slow` tests unless `-m` names the marker."""
    markexpr = config.getoption("markexpr") or ""
    for marker in OPT_IN_MARKERS:
        if marker in markexpr:
            continue
        skip = pytest.mark.skip(reason=f"{marker} test; run with -m {marker}")
        for item in items:
            if marker in item.keywords:
                item.add_marker(skip)


@pytest.fixture(autouse=True)
def no_agent_calls(request, monkeypatch):
    """The pipeline never calls the Claude API in tests, whatever `.env` holds, unless the test is `live`."""
    if "live" in request.keywords:
        return
    from dataclasses import replace

    from offer_engine import config, pipeline

    monkeypatch.setattr(
        pipeline, "load_settings", lambda: replace(config.load_settings(), anthropic_api_key=None)
    )


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """No offer-engine keys in the process environment and a cwd with no `.env`."""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def conn(tmp_path):
    """A migrated database in a temp file."""
    from offer_engine.db import connect, migrate

    connection = connect(tmp_path / "test.db")
    migrate(connection)
    yield connection
    connection.close()


@pytest.fixture(scope="session")
def world_template(tmp_path_factory):
    """A generated 50-Customer world (seed 7), built once per session. Copy it before writing."""
    from offer_engine.db import connect
    from offer_engine.sim.generate import run

    path = tmp_path_factory.mktemp("world") / "world.db"
    connection = connect(path)
    run(connection, 50, months=12, seed=7)
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()
    return path


@pytest.fixture
def world(world_template, tmp_path):
    """A private copy of the generated world, as an open connection."""
    import shutil

    from offer_engine.db import connect

    path = tmp_path / "world.db"
    shutil.copy(world_template, path)
    connection = connect(path)
    yield connection
    connection.close()


@pytest.fixture
def add_offer(conn):
    """Insert a minimal Offer, creating its Customer (and chat, when `chat_id` is given) if missing. Returns the
    Offer's id. Times default to around 1 Dec 2026, with expiry at 4 Dec 10:00."""
    from datetime import datetime

    def add(
        code: str = "POE-AB12CD",
        customer_id: str = "C00042",
        chat_id: int | None = 4242,
        status: str = "sent",
        send_at: datetime = datetime(2026, 12, 1, 10, 0),
        expires_at: datetime = datetime(2026, 12, 4, 10, 0),
        caption: str = "Your fashion picks are waiting.",
    ) -> int:
        conn.execute(
            "INSERT OR IGNORE INTO customers (id, signup_at, city_tier, device, channel, loyalty_tier)"
            " VALUES (?, '2026-01-01T00:00:00', 1, 'android', 'organic', 'silver')",
            (customer_id,),
        )
        if chat_id is not None:
            conn.execute(
                "INSERT OR IGNORE INTO chats (customer_id, chat_id, kind) VALUES (?, ?, 'bot')",
                (customer_id, chat_id),
            )
        cursor = conn.execute(
            "INSERT INTO offers (code, customer_id, offer_type, category, params, created_at, send_at, expires_at,"
            " caption, rule_version, worst_case_cost, expected_cost, status, source)"
            " VALUES (?, ?, 'pct_category', 'fashion', '{\"pct\": 15.0, \"cap\": 300.0}', ?, ?, ?, ?, 1, 300, 60,"
            " ?, 'live')",
            (
                code,
                customer_id,
                send_at.isoformat(),
                send_at.isoformat(),
                expires_at.isoformat(),
                caption,
                status,
            ),
        )
        conn.commit()
        return cursor.lastrowid

    return add
