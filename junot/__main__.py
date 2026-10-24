"""Talk to Junot in the terminal:  uv run python -m junot

The gateway: it reads a line, hands it to the session and the loop, prints the
reply. It knows nothing about how either works, which is the point.
"""

from __future__ import annotations

from junot.client import get_client
from junot.consolidate import maybe_consolidate
from junot.config import load_settings
from junot.loop import run_loop
from junot.memory import Memory
from junot.gate import should_retrieve
from junot.observe import Tracer, compose
from junot.session import Session
from junot.tools import build_registry


def console(kind: str, event: dict) -> None:
    """This gateway's own observer: show tool calls as they happen."""
    if kind == "gate":
        if event["retrieve"]:
            print(f"  [gate] search {event['query']!r}: {event['hits']} note(s)")
        else:
            print(f"  [gate] skip: {event['reason']}")
    if kind == "skills" and event["matched"]:
        print(f"  [skill] {', '.join(event['matched'])}")
    if kind == "consolidation":
        if event.get("error"):
            print(f"  [learn] failed, kept {event['exchanges']} exchange(s) for next time: {event['error']}")
        else:
            print(f"  [learn] {event['exchanges']} exchange(s) -> {len(event['facts'])} new note(s)")
    if kind == "tool":
        mark = "" if event["ok"] else "  (failed)"
        print(f"  [tool] {event['name']}({event['arguments']}){mark}")


def main() -> None:
    settings = load_settings()
    client = get_client(settings)
    memory = Memory(settings.home / "state.db")
    tools = build_registry(memory)
    tracer = Tracer(settings.home / "traces")
    observer = compose(console, tracer)
    session = Session(settings.home, settings.model, memory=memory, observer=observer,
                      skills_dir=settings.skills_dir,
                      gate=lambda message: should_retrieve(client, settings.small_model, message))
    print(f"Junot on {settings.model}. Persona: {settings.home / 'SOUL.md'}. "
          f"Memory: {memory.path} ({len(memory.all())} notes). Ctrl-D to quit.")
    while True:
        try:
            text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            # Learn from what's left before quitting, however few exchanges.
            tracer.start_turn("(quit)")
            maybe_consolidate(client, settings.small_model, memory, every=1, observer=observer)
            tracer.end_turn("")
            return
        if not text:
            continue
        tracer.start_turn(text)
        messages = session.build_messages(text)
        reply = run_loop(client, settings.model, messages, tools, observer=observer)
        session.record(text, messages, reply)
        # Every few exchanges, a small model turns the chat into notes. Inside
        # the turn, so its tokens show up on this turn's receipt.
        maybe_consolidate(client, settings.small_model, memory,
                          every=settings.consolidate_every, observer=observer)
        totals = tracer.end_turn(reply)
        print("junot>", reply)
        # The receipt: what this turn cost, every turn. A number you never see
        # is a number you won't believe when it matters.
        print(f"  [{totals['llm_calls']} llm · {totals['tool_calls']} tool · "
              f"{totals['input_tokens']} in / {totals['output_tokens']} out]")


if __name__ == "__main__":
    main()
