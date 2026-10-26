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


def test_start_runs_both_bots_the_console_and_the_live_view():
    assert [name for name, _ in PROCESSES] == ["offer-bot", "customer-bots", "console", "live"]
    assert dict(PROCESSES)["live"][1:] == ["-m", "offer_engine.live"]
    assert [command[2] for _, command in PROCESSES[:2]] == [
        "offer_engine.offer_bot.app",
        "offer_engine.customer_sim.app",
    ]
    console = PROCESSES[2][1]
    assert console[1:4] == ["-m", "streamlit", "run"]
    assert Path(console[4]).is_file() and console[4].endswith("console/app.py")


class FailingOut(io.StringIO):
    """An output that accepts `ok` writes, then fails like a full disk."""

    def __init__(self, ok: int):
        super().__init__()
        self.ok = ok

    def write(self, text: str) -> int:
        if self.ok <= 0:
            raise OSError(122, "Disk quota exceeded")
        self.ok -= 1
        return super().write(text)


def test_a_failing_output_doesnt_block_the_process():
    import threading

    # 200 KB of output overflows the pipe buffer, so the child blocks unless its output keeps being read.
    child = py("import sys\nfor i in range(4000): print('x' * 50)\nsys.exit(0)")
    out = FailingOut(ok=3)
    result = []
    runner = threading.Thread(target=lambda: result.append(run_processes([("a", child)], out=out, poll=0.05)))
    runner.daemon = True
    runner.start()
    runner.join(timeout=20)
    assert result == [0]
    assert out.getvalue().startswith("[a] " + "x" * 50)
