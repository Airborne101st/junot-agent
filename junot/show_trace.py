"""Read back the latest turn from today's trace:  uv run python -m junot.show_trace

The proof that a trace is enough: this rebuilds what happened in a turn from
the JSONL file alone, with no access to the running agent.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from junot.config import load_settings


def last_turn(path: Path) -> list[dict]:
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not lines:
        return []
    turn_id = lines[-1]["turn_id"]
    return [line for line in lines if line["turn_id"] == turn_id]


def show(events: list[dict]) -> None:
    for e in events:
        kind = e["kind"]
        if kind == "turn_start":
            print(f"{e['ts']}  turn {e['turn_id']}")
            print(f"  you    {e['user']}")
        elif kind == "gate":
            decision = f"search {e['query']!r} -> {e['hits']} note(s)" if e["retrieve"] else "skip"
            print(f"  gate   {decision} ({e['reason']}); {e['input_tokens']} in / {e['output_tokens']} out")
        elif kind == "consolidation":
            if e.get("error"):
                print(f"  learn  {e['exchanges']} exchange(s) FAILED: {e['error']} (kept for next time)")
            else:
                print(f"  learn  {e['exchanges']} exchange(s) -> {len(e['facts'])} note(s); "
                      f"{e['input_tokens']} in / {e['output_tokens']} out")
                for fact in e["facts"]:
                    print(f"         + {fact}")
                if e["episode"]:
                    print(f"         episode: {e['episode']}")
        elif kind == "llm":
            label = "final" if e["final"] else f"call {e['iteration']}"
            print(f"  llm    {label}: {e['input_tokens']} in / {e['output_tokens']} out, "
                  f"{e['tool_calls']} tool call(s)")
        elif kind == "tool":
            status = "ok" if e["ok"] else "FAILED"
            print(f"  tool   {e['name']}({e['arguments']}) {status} in {e['duration_ms']} ms")
            print(f"         -> {e['output'][:300]}")
        elif kind == "turn_end":
            print(f"  reply  {e['reply'][:300]}")
            print(f"  total  {e['llm_calls']} llm call(s), {e['tool_calls']} tool call(s), "
                  f"{e['input_tokens']} in / {e['output_tokens']} out")


if __name__ == "__main__":
    folder = load_settings().home / "traces"
    path = folder / f"{datetime.now().astimezone():%Y-%m-%d}.jsonl"
    if not path.exists():
        sys.exit(f"No trace for today yet ({path}). Talk to Junot first.")
    show(last_turn(path))
