"""Talk to Junot in the terminal:  uv run python -m junot

The gateway: it reads a line, hands it to the session and the loop, prints the
reply. It knows nothing about how either works, which is the point.
"""

from __future__ import annotations

from junot.client import get_client
from junot.config import load_settings
from junot.loop import run_loop
from junot.session import Session
from junot.tools import build_registry


def main() -> None:
    settings = load_settings()
    client = get_client(settings)
    tools = build_registry()
    session = Session(settings.home, settings.model)
    print(f"Junot on {settings.model}. Persona: {settings.home / 'SOUL.md'}. Ctrl-D to quit.")
    while True:
        try:
            text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not text:
            continue
        messages = session.build_messages(text)
        reply = run_loop(client, settings.model, messages, tools)
        session.record(text, messages, reply)
        print("junot>", reply)


if __name__ == "__main__":
    main()
