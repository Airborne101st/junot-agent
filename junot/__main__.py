"""Talk to Junot in the terminal:  uv run python -m junot

The gateway: it reads a line, hands it to the session and the loop, prints the
reply. It knows nothing about how either works, which is the point.
"""

from __future__ import annotations

from junot.client import get_client
from junot.config import load_settings
from junot.loop import run_loop
from junot.observe import Tracer, compose
from junot.session import Session
from junot.tools import build_registry


def console(kind: str, event: dict) -> None:
    """This gateway's own observer: show tool calls as they happen."""
    if kind == "tool":
        mark = "" if event["ok"] else "  (failed)"
        print(f"  [tool] {event['name']}({event['arguments']}){mark}")


def main() -> None:
    settings = load_settings()
    client = get_client(settings)
    tools = build_registry()
    session = Session(settings.home, settings.model)
    tracer = Tracer(settings.home / "traces")
    observer = compose(console, tracer)
    print(f"Junot on {settings.model}. Persona: {settings.home / 'SOUL.md'}. Ctrl-D to quit.")
    while True:
        try:
            text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not text:
            continue
        tracer.start_turn(text)
        messages = session.build_messages(text)
        reply = run_loop(client, settings.model, messages, tools, observer=observer)
        session.record(text, messages, reply)
        totals = tracer.end_turn(reply)
        print("junot>", reply)
        # The receipt: what this turn cost, every turn. A number you never see
        # is a number you won't believe when it matters.
        print(f"  [{totals['llm_calls']} llm · {totals['tool_calls']} tool · "
              f"{totals['input_tokens']} in / {totals['output_tokens']} out]")


if __name__ == "__main__":
    main()
