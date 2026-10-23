from datetime import datetime, timedelta, timezone

import pytest

from offer_engine import clock
from offer_engine.cli import main
from offer_engine.db import connect


def test_default_start(conn):
    assert clock.now(conn) == datetime(2026, 12, 1, 0, 0) == clock.START


def test_advance_by_hours_and_days(conn):
    assert clock.advance(conn, 5) == datetime(2026, 12, 1, 5, 0)
    assert clock.advance(conn, 24) == datetime(2026, 12, 2, 5, 0)
    assert clock.now(conn) == datetime(2026, 12, 2, 5, 0)


def test_set_now(conn):
    clock.set_now(conn, datetime(2027, 1, 5, 10, 30))
    assert clock.now(conn) == datetime(2027, 1, 5, 10, 30)


def test_rejects_backwards_and_aware_times(conn):
    with pytest.raises(ValueError):
        clock.advance(conn, -1)
    with pytest.raises(ValueError):
        clock.set_now(conn, datetime(2027, 1, 1, tzinfo=timezone(timedelta(hours=5, minutes=30))))


def test_persists_across_connections(tmp_path):
    from offer_engine.db import migrate

    path = tmp_path / "x.db"
    first = connect(path)
    migrate(first)
    clock.advance(first, 48)
    first.close()
    assert clock.now(connect(path)) == datetime(2026, 12, 3, 0, 0)


def test_cli_show_and_advance(clean_env, capsys):
    assert main(["db", "init"]) == 0
    assert main(["clock", "show"]) == 0
    assert main(["clock", "advance", "--days", "1"]) == 0
    assert main(["clock", "advance", "--hours", "6"]) == 0
    assert main(["clock", "show"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[1:] == [
        "2026-12-01 00:00",
        "2026-12-02 00:00",
        "nothing happened",
        "2026-12-02 06:00",
        "nothing happened",
        "2026-12-02 06:00",
    ]


def test_cli_advance_prints_the_days_counts(clean_env, capsys):
    assert main(["generate", "--customers", "60", "--months", "2"]) == 0
    capsys.readouterr()
    assert main(["clock", "advance", "--days", "1", "--seed", "3"]) == 0
    date_line, counts = capsys.readouterr().out.splitlines()
    assert date_line == "2026-12-02 00:00"
    assert counts.startswith("sessions ") and "product_views" in counts


def test_cli_needs_db_init(clean_env):
    with pytest.raises(SystemExit, match="db init"):
        main(["clock", "show"])


def test_cli_advance_needs_one_amount(clean_env):
    main(["db", "init"])
    with pytest.raises(SystemExit):
        main(["clock", "advance"])
    with pytest.raises(SystemExit):
        main(["clock", "advance", "--days", "1", "--hours", "2"])
