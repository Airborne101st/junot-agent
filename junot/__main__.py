"""Talk to Junot in the terminal:  uv run python -m junot

The terminal gateway. It reads a line, calls Junot.respond(), prints the
reply and the receipt. Everything else (the loop, memory, the gate, skills,
consolidation, the trace) lives behind respond(), so this file only knows
how to talk to a terminal.
"""

from __future__ import annotations

from junot.app import Junot
from junot.config import load_settings


def console(kind: str, event: dict) -> None:
    """This gateway's own observer: show what Junot is doing as it happens."""
    if kind == "gate":
        if event["retrieve"]:
            print(f"  [gate] search {event['query']!r}: {event['hits']} note(s)")
        else:
            print(f"  [gate] skip: {event['reason']}")
    elif kind == "skills" and event["matched"]:
        print(f"  [skill] {', '.join(event['matched'])}")
    elif kind == "consolidation":
        if event.get("error"):
            print(f"  [learn] failed, kept {event['exchanges']} exchange(s) for next time: {event['error']}")
        else:
            print(f"  [learn] {event['exchanges']} exchange(s) -> {len(event['facts'])} new note(s)")
    elif kind == "tool":
        mark = "" if event["ok"] else "  (failed)"
        print(f"  [tool] {event['name']}({event['arguments']}){mark}")


def receipt(totals: dict) -> str:
    """One line: what this turn cost. A number you never see is a number you
    won't believe when it matters."""
    return (f"[{totals.get('llm_calls', 0)} llm · {totals.get('tool_calls', 0)} tool · "
            f"{totals.get('input_tokens', 0)} in / {totals.get('output_tokens', 0)} out]")


def main() -> None:
    settings = load_settings()
    junot = Junot(settings, observer=console)
    print(f"Junot on {settings.model}. Persona: {settings.home / 'SOUL.md'}. Ctrl-D to quit.")
    try:
        while True:
            try:
                text = input("\nyou> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if text:
                turn = junot.respond(text, conversation="cli")
                print("junot>", turn.reply)
                print("  " + receipt(turn.totals))
    finally:
        junot.close()


if __name__ == "__main__":
    main()
