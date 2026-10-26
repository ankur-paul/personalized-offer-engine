"""Record Claude's answers and play them back, so the demo gets the same picks and captions every time (T36, QnA
Q45).

`ReplayClient` stands in for `anthropic.Anthropic`: only `.messages.create(**kwargs)` is used. A request is keyed
by the SHA-256 of `model`, `system`, `tools` and `messages`; `max_tokens`, `timeout` and the like don't change the
key. Recordings are one JSON object per line: `{key, model, request, response}`.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from offer_engine.config import AGENT_MODES as MODES

DEFAULT_PATH = Path("demo/agent_recordings.jsonl")
KEY_FIELDS = ("model", "system", "tools", "messages")
BLOCK_FIELDS = ("type", "name", "input", "text")


class ReplayMiss(LookupError):
    """Replay found no recording for the request and has no client to ask."""


def request_key(kwargs: dict[str, Any]) -> str:
    request = {k: kwargs.get(k) for k in KEY_FIELDS}
    canonical = json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def to_json(response: Any) -> dict[str, Any]:
    """The parts of a Messages API response the agents read."""
    content = []
    for block in response.content:
        stored = {}
        for name in BLOCK_FIELDS:
            value = getattr(block, name, None)
            if value is not None:
                stored[name] = dict(value) if name == "input" else value
        content.append(stored)
    return {"stop_reason": response.stop_reason, "content": content}


def from_json(stored: dict[str, Any]) -> SimpleNamespace:
    content = [
        SimpleNamespace(**{name: block.get(name) for name in BLOCK_FIELDS}) for block in stored["content"]
    ]
    return SimpleNamespace(stop_reason=stored["stop_reason"], content=content)


class ReplayClient:
    def __init__(self, real: Any | None, mode: str, path: Path = DEFAULT_PATH):
        if mode not in MODES:
            raise ValueError(f"agent mode must be one of {', '.join(MODES)}, got {mode!r}")
        self.real = real
        self.mode = mode
        self.path = path
        self.messages = SimpleNamespace(create=self._create)
        self._lock = threading.Lock()
        self._recordings: dict[str, dict[str, Any]] = {}
        self._read_bytes = 0

    def _create(self, **kwargs: Any) -> Any:
        if self.mode == "replay":
            stored = self._lookup(request_key(kwargs))
            if stored is not None:
                return from_json(stored)
            if self.real is None:
                raise ReplayMiss(f"no recorded answer for this {kwargs.get('model')} request in {self.path}")
        if self.real is None:
            raise RuntimeError("no Claude client: set ANTHROPIC_API_KEY")
        response = self.real.messages.create(**kwargs)
        if self.mode != "live":
            self._record(kwargs, response)
        return response

    def _lookup(self, key: str) -> dict[str, Any] | None:
        """The recorded response for `key`, reading lines another process appended since the last lookup."""
        with self._lock:
            size = self.path.stat().st_size if self.path.is_file() else 0
            if size < self._read_bytes:
                # The file was emptied or replaced: start over.
                self._recordings, self._read_bytes = {}, 0
            if size > self._read_bytes:
                with self.path.open("rb") as f:
                    f.seek(self._read_bytes)
                    new = f.read()
                # A line still being written has no newline yet; it is read next time.
                whole = new[: new.rfind(b"\n") + 1]
                for line in whole.splitlines():
                    if line.strip():
                        entry = json.loads(line)
                        self._recordings[entry["key"]] = entry["response"]
                self._read_bytes += len(whole)
            return self._recordings.get(key)

    def _record(self, kwargs: dict[str, Any], response: Any) -> None:
        entry = {
            "key": request_key(kwargs),
            "model": kwargs.get("model"),
            "request": {k: kwargs.get(k) for k in KEY_FIELDS},
            "response": to_json(response),
        }
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line)
