import io
import sys
import time
from pathlib import Path

from offer_engine.commands.start import PROCESSES, run_processes


def py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_output_is_prefixed_and_clean_exits_end_the_run():
    out = io.StringIO()
    code = run_processes([("a", py("print('hello')")), ("b", py("print('world')"))], out=out, poll=0.05)
    text = out.getvalue()
    assert code == 0
    assert "[a] hello\n" in text and "[b] world\n" in text


def test_a_failing_process_stops_the_others():
    out = io.StringIO()
    started = time.monotonic()
    code = run_processes(
        [("sleeper", py("import time; time.sleep(60)")), ("crasher", py("raise SystemExit(3)"))],
        out=out,
        poll=0.05,
    )
    assert code == 3
    assert "[start] crasher exited with code 3" in out.getvalue()
    assert time.monotonic() - started < 10


def test_start_runs_both_bots_and_the_console():
    assert [name for name, _ in PROCESSES] == ["offer-bot", "customer-bots", "console"]
    assert [command[2] for _, command in PROCESSES[:2]] == ["offer_engine.offer_bot.app", "offer_engine.customer_sim.app"]
    console = PROCESSES[2][1]
    assert console[1:4] == ["-m", "streamlit", "run"]
    assert Path(console[4]).is_file() and console[4].endswith("console/app.py")
