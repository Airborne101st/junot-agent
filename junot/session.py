"""The session: working memory, rebuilt for every turn.

Everything the model knows on a turn comes from here:

    system prompt  = SOUL.md (who Junot is) + the clock + which model it is
  + history        = earlier turns: what you said and what Junot replied,
                     with a short note of the tools it used
  + the new message

The model remembers nothing between API calls. If it isn't in these
messages, it doesn't exist for the model.

YOUR CODE (step 3). See docs/steps/03-the-session.md.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path


DEFAULT_SOUL = "You are Junot, my Aide De Camp, You shall always refer to me as the 'First Consul'. Use 20th century military language with me."


def tool_note(turn: list[dict]) -> str:
    """A one-line record of the tools a turn used, for history.

    `turn` is the messages list after run_loop. Looks at the messages after
    the last user message. Returns "" when no tool ran, otherwise
        [tools used: get_time({"timezone": "Asia/Tokyo"}) -> 2026-10-15T14:30:00+09:00]
    with several calls joined by "; " and each output cut to 200 characters.
    """
    # 1. This turn starts at the last user message; everything before it is
    #    history from earlier turns, whose tools were noted back then.
    last = 0
    for i, m in enumerate(turn):
        if m["role"] == "user":
            last = i
    this_turn = turn[last:]

    # 2. Each tool result, by the id of the call it answers.
    outputs = {m["tool_call_id"]: m["content"] for m in this_turn if m["role"] == "tool"}

    # 3. One entry per call, in the order the model made them.
    entries = []
    for m in this_turn:
        for call in m.get("tool_calls") or []:
            name = call["function"]["name"]
            arguments = call["function"]["arguments"]
            output = outputs.get(call["id"], "")
            if len(output) > 200:
                output = output[:200] + "..."
            entries.append(f"{name}({arguments}) -> {output}")

    # 4. Nothing ran: no note at all, so the reply is stored as it is.
    if not entries:
        return ""
    return "[tools used: " + "; ".join(entries) + "]"


class Session:
    def __init__(self, home: Path, model: str,
                 clock: Callable[[], datetime] = lambda: datetime.now().astimezone()) -> None:
        self.home = home
        self.model = model
        self.clock = clock
        self.history = []

    def soul(self) -> str:
        """SOUL.md's text, creating it from DEFAULT_SOUL if it doesn't exist."""
        soul_file_path = self.home / "SOUL.md"
        if not soul_file_path.exists():
            soul_file_path.write_text(DEFAULT_SOUL, encoding="utf-8")
        return soul_file_path.read_text(encoding="utf-8")

    def build_system(self) -> str:
        """SOUL.md + the current time (with its UTC offset) + the model name."""
        now = self.clock()
        return '\n'.join([self.soul(), f"Right now it is {now.strftime("%A")}, {now.isoformat(timespec="minutes")}", f"You are running on the model {self.model}"])

    def build_messages(self, user_message: str) -> list[dict]:
        """[system] + history + [user]: a NEW list, ready for run_loop."""
        return [{"role": "system", "content": self.build_system()},
                *self.history,
                {"role": "user", "content": user_message}]

    def record(self, user_message: str, turn: list[dict], reply: str) -> None:
        """After a turn: add the user message and the reply (plus its tool
        note) to history. Raw tool messages are never stored."""
        note = tool_note(turn)
        self.history.append({"role": "user", "content": user_message})
        if note:
            content = reply + '\n' + note
        else:
            content = reply
        self.history.append({"role": "assistant", "content": content})
