"""Observing a turn: what happened, in order, without the loop knowing who's watching.

An observer is any function `observer(kind, event)`. The loop calls it for
every model call ("llm") and every tool call ("tool"). The terminal prints
some of it, the Tracer writes all of it to a file, and later a dashboard
could draw it. The loop never imports any of them.

YOUR CODE (step 4). See docs/steps/04-observe.md.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

Observer = Callable[[str, dict], None]

# ---- step 12: what a trace may keep -------------------------------------------
# A trace keeps everything, forever, readable by any account on the Mac
# (-rw-r--r--). That's what made it useful in step 4, and what makes it a risk.

MASK = "[redacted]"

# A value under one of these keys is masked whatever it looks like.
SECRET_KEY = re.compile(r"(password|passwd|passcode|secret|token|api_?key|authorization|cookie|pin)$", re.I)

# Values that look like credentials, wherever they appear in text.
SECRET_TEXT = [
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),                 # Google / Gemini API keys
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),                # OpenAI-style keys
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_\-]{30,}\b"),          # Telegram bot tokens
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"),      # Authorization: Bearer ...
]
# "my password is hunter2", "pin: 4721", and the same keys inside a JSON string
# such as a tool call's arguments: '{"password": "hunter2"}'.
SECRET_PHRASE = re.compile(
    r'(?i)("?\b(?:password|passwd|passcode|pin|api[_ ]?key|secret|token)"?\s*(?:is|:|=)\s*"?)([^\s",}]+)')


def redact(value):
    """A copy of `value` with secrets masked: by key in dicts, by shape in text."""
    if isinstance(value, dict):
        return {key: MASK if SECRET_KEY.search(str(key)) and value[key] not in (None, "") else redact(v)
                for key, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        for pattern in SECRET_TEXT:
            value = pattern.sub(MASK, value)
        return SECRET_PHRASE.sub(lambda m: m.group(1) + MASK, value)
    return value


def compose(*observers: Observer | None) -> Observer:
    """One observer that calls each given observer in order. None entries are
    skipped, and an observer that raises never stops the others or the turn."""
    active = [o for o in observers if o is not None]

    def run(kind: str, event: dict) -> None:
        for observer in active:
            # The try is per observer, not around the loop: one broken
            # observer must not silence the ones after it.
            try:
                observer(kind, event)
            except Exception:
                pass

    return run


class Tracer:
    """Writes every event of every turn as one JSON line, to one file per day:
    <folder>/<YYYY-MM-DD>.jsonl. Use the instance itself as an observer."""

    def __init__(self, folder: Path,
                 clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
                 keep_days: int = 30) -> None:
        """`keep_days`: trace files older than this are deleted when a Tracer
        starts. 0 keeps them forever."""
        self.folder = Path(folder)
        self.clock = clock
        self.keep_days = keep_days
        self.turn_id = ""
        self.totals = self._zero()
        self._tidy()

    def _tidy(self) -> None:
        """Step 12: owner-only permissions, and retention. Runs once, at start."""
        if not self.folder.is_dir():
            return
        os.chmod(self.folder, 0o700)            # rwx for you, nothing for anyone else
        oldest = self.clock().date() - timedelta(days=self.keep_days)
        for path in self.folder.glob("*.jsonl"):
            try:
                day = datetime.strptime(path.stem, "%Y-%m-%d").date()
            except ValueError:
                continue                         # not a trace file: not ours to touch
            if self.keep_days and day < oldest:
                path.unlink()
            else:
                os.chmod(path, 0o600)            # files from before step 12 were -rw-r--r--

    @staticmethod
    def _zero() -> dict:
        return {"llm_calls": 0, "tool_calls": 0, "input_tokens": 0, "output_tokens": 0}

    def _write(self, kind: str, data: dict) -> None:
        """Append one line. The date comes from the clock at write time, so a
        turn just after midnight lands in the new day's file."""
        now = self.clock()
        if not self.folder.is_dir():
            self.folder.mkdir(parents=True, mode=0o700)
        line = redact({"ts": now.isoformat(), "turn_id": self.turn_id, "kind": kind, **data})
        # os.open with mode 0o600: a new file is created owner-only from its
        # first byte, rather than world-readable and fixed later.
        fd = os.open(self.folder / f"{now:%Y-%m-%d}.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def start_turn(self, user_message: str, conversation: str | None = None) -> str:
        """Begin a turn: a new turn_id, and a "turn_start" line. Returns the id.
        `conversation` says which chat it came from ("cli", "web", "telegram:42")."""
        self.turn_id = uuid.uuid4().hex[:12]
        self.totals = self._zero()
        start = {"user": user_message}
        if conversation is not None:
            start["conversation"] = conversation
        self._write("turn_start", start)
        return self.turn_id

    def __call__(self, kind: str, event: dict) -> None:
        """The observer: write one line, and count what the turn used."""
        if kind == "llm":
            self.totals["llm_calls"] += 1
        if kind in ("llm", "gate", "consolidation"):
            # The gate is a model call too: its tokens are part of what the
            # turn cost, even though it isn't one of the loop's calls.
            self.totals["input_tokens"] += event.get("input_tokens", 0)
            self.totals["output_tokens"] += event.get("output_tokens", 0)
        elif kind == "tool":
            self.totals["tool_calls"] += 1
        self._write(kind, event)

    def end_turn(self, reply: str) -> dict:
        """End the turn: write a "turn_end" line with the totals, and return them."""
        result = {"reply": reply, **self.totals}
        self._write("turn_end", result)
        return result
