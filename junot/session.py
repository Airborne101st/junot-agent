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

from junot.gate import Decision
from junot.skills import load_skills, match_skills


DEFAULT_SOUL = "You are Junot, my Aide De Camp, You shall always refer to me as the 'First Consul'. Use 1700s colonial american english with me. Be honest in your responses and never claim anything which is not backed by proof."


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
                 clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
                 memory=None, gate=None, observer=None, skills_dir: Path | None = None) -> None:
        self.home = home
        self.model = model
        self.clock = clock
        self.history = []
        self.memory = memory
        self.gate = gate
        self.skills_dir = skills_dir
        self.observer = observer or (lambda kind, event: None)

    def recall(self, user_message: str) -> str:
        """Ask the gate, search if it says yes, report the decision, and return
        the memory section for the system prompt ("" when nothing was found)."""
        if not self.gate:
            # No gate behaves like a gate that always says yes: fail open.
            decision = Decision(True, user_message, "no gate")
        else:
            decision = self.gate(user_message)
        hits = self.memory.search(decision.query, limit=5) if decision.retrieve else []

        self.observer("gate", {
            "retrieve": decision.retrieve,
            "query": decision.query,
            "reason": decision.reason,
            "hits": len(hits),
            "input_tokens": decision.input_tokens,
            "output_tokens": decision.output_tokens,
        })

        if not hits:
            return ""
        # The #id lets the model forget or correct a recalled note (step 13).
        lines = [f"- #{hit['id']} [{hit['subject']}] {hit['content']}" for hit in hits]
        # Say the search already happened. Without this the main model ran
        # search_notes again for notes that were already in front of it.
        return "\n".join([
            f"Your notes were already searched for this message (query: {decision.query!r}). They hold:",
            *lines,
            "Answer from these. Call search_notes only if they don't answer the question.",
        ])

    def soul(self) -> str:
        """SOUL.md's text, creating it from DEFAULT_SOUL if it doesn't exist."""
        soul_file_path = self.home / "SOUL.md"
        if not soul_file_path.exists():
            soul_file_path.write_text(DEFAULT_SOUL, encoding="utf-8")
        return soul_file_path.read_text(encoding="utf-8")

    def build_system(self, user_message: str = "") -> str:
        """SOUL.md + the current time (with its UTC offset) + the model name,
        and the recalled notes when there is memory and a message to judge."""
        now = self.clock()
        parts = [self.soul(),
                 f"Right now it is {now.strftime('%A')}, {now.isoformat(timespec='minutes')}",
                 f"You are running on the model {self.model}"]
        if self.memory is not None and user_message:
            section = self.recall(user_message)
            if section:
                parts.append(section)
        if self.skills_dir is not None and user_message:
            parts.extend(self.skill_sections(user_message))
        return "\n".join(parts)

    def skill_sections(self, user_message: str) -> list[str]:
        """The bodies of the skills this message matches, one section each.
        The folder is read every turn, like SOUL.md: a SKILL.md added while
        the REPL runs works on the next message."""
        matched = match_skills(load_skills(self.skills_dir), user_message)
        # Reported even when nothing matched, so the trace shows the check ran.
        self.observer("skills", {"matched": [skill.name for skill in matched]})
        return [f"Follow this skill for this request ({skill.name}):\n{skill.body}" for skill in matched]

    def build_messages(self, user_message: str) -> list[dict]:
        """[system] + history + [user]: a NEW list, ready for run_loop."""
        return [{"role": "system", "content": self.build_system(user_message)},
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
        # Step 7: the chat log outlives the REPL, so consolidation can learn
        # from exchanges across sessions. Same text as history, note included.
        if self.memory is not None:
            self.memory.log_exchange(user_message, content)
