"""Observing a turn: what happened, in order, without the loop knowing who's watching.

An observer is any function `observer(kind, event)`. The loop calls it for
every model call ("llm") and every tool call ("tool"). The terminal prints
some of it, the Tracer writes all of it to a file, and later a dashboard
could draw it. The loop never imports any of them.

YOUR CODE (step 4). See docs/steps/04-observe.md.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

Observer = Callable[[str, dict], None]


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
                 clock: Callable[[], datetime] = lambda: datetime.now().astimezone()) -> None:
        self.folder = Path(folder)
        self.clock = clock
        self.turn_id = ""
        self.totals = self._zero()

    @staticmethod
    def _zero() -> dict:
        return {"llm_calls": 0, "tool_calls": 0, "input_tokens": 0, "output_tokens": 0}

    def _write(self, kind: str, data: dict) -> None:
        """Append one line. The date comes from the clock at write time, so a
        turn just after midnight lands in the new day's file."""
        now = self.clock()
        self.folder.mkdir(parents=True, exist_ok=True)
        line = {"ts": now.isoformat(), "turn_id": self.turn_id, "kind": kind, **data}
        with open(self.folder / f"{now:%Y-%m-%d}.jsonl", "a", encoding="utf-8") as f:
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
