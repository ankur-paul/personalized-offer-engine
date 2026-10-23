import pytest


@pytest.fixture(scope="session")
def world_2k(tmp_path_factory):
    """A generated 2,000-Customer world (seed 7) and its path, built once per session. Read only."""
    from offer_engine.db import connect
    from offer_engine.sim.generate import run

    path = tmp_path_factory.mktemp("2k") / "world.db"
    conn = connect(path)
    run(conn, 2_000, months=12, seed=7)
    yield conn, path
    conn.close()
