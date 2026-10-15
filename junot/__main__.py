"""Talk to Junot in the terminal:  uv run python -m junot

The gateway: it reads a line, hands it to the loop, prints the reply. It knows
nothing about how the loop works, which is the point.
"""

from __future__ import annotations

from junot.client import get_client
from junot.config import load_settings
from junot.loop import run_loop
from junot.tools import build_registry

SYSTEM = "You are Junot, a concise personal assistant. Use tools when they help."


def main() -> None:
    settings = load_settings()
    client = get_client(settings)
    tools = build_registry()
    messages: list[dict] = [{"role": "system", "content": SYSTEM}]
    print(f"Junot on {settings.model}. Ctrl-D to quit.")
    while True:
        try:
            text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not text:
            continue
        messages.append({"role": "user", "content": text})
        print("junot>", run_loop(client, settings.model, messages, tools))


if __name__ == "__main__":
    main()
