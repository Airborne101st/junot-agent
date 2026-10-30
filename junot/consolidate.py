"""Consolidation: learning notes from the conversation, every few exchanges.

Until now Junot keeps a fact only when it decides to call save_note, which in
practice means only when you say "remember". Most of what's worth keeping is
said in passing: "I'm flying to Pune on Friday", "Swapnil is my brother".

Every N exchanges, one call to the small model reads the exchanges nobody has
consolidated yet and writes two things: durable facts, which go into the
notes the gate searches, and one episode, a dated sentence of what happened.
Batching N exchanges is cheaper than a call per message, and gives the
summarizer enough context to tell a fact from small talk.

If anything goes wrong, nothing is lost: the exchanges stay unconsolidated,
and the next batch tries again.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from junot.loop import _tokens

# Every rule here comes from a real note in data/state.db: "June 20th" said
# nothing about whose birthday, "First Consul's Birthday" wrote the persona's
# name into the data, and "Flying to Pune on October 23" lost the word
# "Friday" that a later search needed.
SUMMARIZER_PROMPT = """You turn a personal assistant's recent conversation with its user into long-term notes.

Extract:
1. Durable facts about the user, their people, plans, dates and preferences: only what is
   worth remembering in a month. Skip small talk, one-off questions, and anything about the
   assistant itself or its tools.
2. One sentence summarising what happened in these exchanges: the episode.

Rules for each fact:
- Only what the user said or confirmed. Never take a fact from the assistant's own words.
- Write the content as one sentence that names its subject and reads on its own:
  "The user's brother Swapnil's birthday is June 20.", never just "June 20".
- Call the person "the user", never a nickname or title the assistant uses for them.
- Write dates in full with the weekday ("Friday, October 23, 2026"), never "tomorrow"
  or "next week".
- Don't repeat anything in the list of facts already known.
- If the user asked to forget or delete something in these exchanges, store nothing about
  it, not even what they said about it in earlier exchanges.

Facts already known:
{known}

Reply with ONLY this JSON, nothing else:
{{"facts": [{{"subject": "<who or what>", "content": "<one sentence>"}}], "episode": "<one sentence>"}}

Exchanges:
{exchanges}"""


@dataclass
class ConsolidationResult:
    facts: list[dict] = field(default_factory=list)   # the facts actually stored
    episode: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


def _same(text: str) -> str:
    """The form two facts are compared in: case and extra spaces ignored."""
    return " ".join(text.split()).casefold()


def maybe_consolidate(client, model: str, memory, every: int = 6,
                      observer=None) -> ConsolidationResult | None:
    """If at least `every` exchanges are waiting, distill them into facts and
    an episode, and mark them consolidated. None when not due, or when the
    call or its JSON failed (the exchanges then wait for the next batch).
    Never raises."""
    notify = observer or (lambda kind, event: None)
    rows = memory.unconsolidated()
    if len(rows) < every:
        return None

    input_tokens = output_tokens = 0
    # Decide everything inside the try, write nothing until after it: a
    # failure halfway must not leave facts stored for exchanges that then
    # wait, and get consolidated (and stored) a second time.
    try:
        stored = memory.all()
        known = "\n".join(f"- {fact['content']}" for fact in stored) or "(nothing yet)"
        exchanges = "\n\n".join(f"User: {row['user']}\nAssistant: {row['assistant']}" for row in rows)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": SUMMARIZER_PROMPT.format(known=known, exchanges=exchanges)}],
        )
        input_tokens, output_tokens = _tokens(response)
        text = response.choices[0].message.content or ""
        data = json.loads(text[text.index("{"): text.rindex("}") + 1])

        seen = {_same(fact["content"]) for fact in stored}
        kept = []
        for fact in data.get("facts") or []:
            if not isinstance(fact, dict):
                continue
            content = (fact.get("content") or "").strip()
            if not content or _same(content) in seen:
                continue
            seen.add(_same(content))
            kept.append({"subject": (fact.get("subject") or "").strip(), "content": content})
        episode = (data.get("episode") or "").strip()
    except Exception as exc:
        # Report it: a fallback nobody can see hides a summarizer that never worked.
        notify("consolidation", {"exchanges": len(rows), "facts": [], "episode": "",
                                 "input_tokens": input_tokens, "output_tokens": output_tokens,
                                 "error": f"{type(exc).__name__}: {exc}"})
        return None

    for fact in kept:
        memory.add(fact["subject"], fact["content"])
    if episode:
        memory.add_episode(memory.clock().date().isoformat(), episode)
    memory.mark_consolidated([row["id"] for row in rows])

    notify("consolidation", {"exchanges": len(rows), "facts": [fact["content"] for fact in kept],
                             "episode": episode, "input_tokens": input_tokens,
                             "output_tokens": output_tokens})
    return ConsolidationResult(kept, episode, input_tokens, output_tokens)
