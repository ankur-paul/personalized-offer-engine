import io
import sys
import time

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


def test_start_runs_both_bots():
    modules = [command[-1] for _, command in PROCESSES]
    assert modules == ["offer_engine.offer_bot.app", "offer_engine.customer_sim.app"]
