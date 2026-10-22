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
