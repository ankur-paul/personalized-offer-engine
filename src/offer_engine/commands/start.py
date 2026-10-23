"""`offer-engine start`: run every long-running process together, with prefixed output, until Ctrl-C."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TextIO

CONSOLE_APP = Path(__file__).resolve().parents[3] / "console" / "app.py"

# (name, command). One entry per line, so tickets add their own process without conflicting.
PROCESSES = [
    ("offer-bot", [sys.executable, "-m", "offer_engine.offer_bot.app"]),
    ("customer-bots", [sys.executable, "-m", "offer_engine.customer_sim.app"]),
    ("console", [sys.executable, "-m", "streamlit", "run", str(CONSOLE_APP), "--server.headless", "true"]),
]
STOP_TIMEOUT = 5.0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "start", help="run the Offer Bot, the Customer Bot simulator and the console"
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    return run_processes(PROCESSES)


def _pump(name: str, stream: TextIO, out: TextIO, lock: threading.Lock) -> None:
    for line in stream:
        with lock:
            out.write(f"[{name}] {line}")
            out.flush()


def _stop(procs: list[subprocess.Popen]) -> None:
    for proc in procs:
        if proc.poll() is None:
            proc.terminate()
    deadline = time.monotonic() + STOP_TIMEOUT
    for proc in procs:
        try:
            proc.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def run_processes(processes: list[tuple[str, list[str]]], out: TextIO = sys.stdout, poll: float = 0.2) -> int:
    """Start each process and prefix its output with its name. A process that exits 0 just ends; one that fails
    stops the rest and its code is returned. Ctrl-C stops all and returns 130."""
    lock = threading.Lock()
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    procs: list[subprocess.Popen] = []
    pumps: list[threading.Thread] = []
    names: dict[int, str] = {}
    code = 0
    try:
        for name, command in processes:
            proc = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env
            )
            procs.append(proc)
            names[proc.pid] = name
            pump = threading.Thread(target=_pump, args=(name, proc.stdout, out, lock), daemon=True)
            pump.start()
            pumps.append(pump)
        running = list(procs)
        while running:
            time.sleep(poll)
            for proc in list(running):
                status = proc.poll()
                if status is None:
                    continue
                running.remove(proc)
                with lock:
                    out.write(f"[start] {names[proc.pid]} exited with code {status}\n")
                if status != 0:
                    code = status
                    running = []
                    break
    except KeyboardInterrupt:
        code = 130
    finally:
        _stop(procs)
        for pump in pumps:
            pump.join(timeout=1.0)
    return code
