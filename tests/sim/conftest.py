import pytest


@pytest.fixture(scope="session")
def world_2k(tmp_path_factory, worker_id):
    """A generated 2,000-Customer world (seed 7) and its path, built once per test run. Read only.

    It takes about a minute to build, so under pytest-xdist the first worker builds it in the temp directory all
    workers share, behind a file lock, and the others wait and reuse it."""
    from filelock import FileLock

    from offer_engine.db import connect
    from offer_engine.sim.generate import run

    root = tmp_path_factory.getbasetemp()
    if worker_id != "master":
        root = root.parent  # each worker's base temp sits in one shared directory
    path = root / "world_2k" / "world.db"
    path.parent.mkdir(exist_ok=True)
    with FileLock(f"{path}.lock"):
        if not path.exists():
            building = path.with_name("building.db")
            conn = connect(building)
            run(conn, 2_000, months=12, seed=7)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
            building.rename(path)
    conn = connect(path)
    yield conn, path
    conn.close()
