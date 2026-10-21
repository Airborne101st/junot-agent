"""The retrieval gate: should this message look in memory at all, and for what?

Step 5's experiments showed the cost of leaving that to the main model: six
searches for "what do you know about my family?", and almost 3,900 tokens to
answer "do I have a sibling?". And searching every message's raw words
returns notes that match "my" and "is".

So before the main model starts, one call to a small, cheap model answers a
single narrow question, and writes the search keywords if the answer is yes.
If anything goes wrong, the gate fails OPEN: it searches anyway. A note you
didn't need costs a few tokens; a note you needed and skipped costs a wrong
answer.

YOUR CODE (step 6). See docs/steps/06-gate.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from junot.loop import _tokens

# TODO: the instruction for the small model. It must reply with ONLY a JSON
# object: {"retrieve": true/false, "query": "<keywords>", "reason": "<few words>"}.
# Put {message} where the user's message goes.
GATE_PROMPT = ('Judge the user message and decide weather answering this prompt need the facts '
               'user told the assistant before. for example: information about people, dates, plans, past events. '
               'Answer only in this specific JSON format: {{"retrieve": true/false, "query": "...", "reason": "..."}} '
                'retrieve should be false when: user is asking about general knowledge, arithmetic etc. '
                'retrieve should be true when: user is asking about their life or information which was stored earlier. '
                'reason should be a specific reason behind your decision. '
                'then build a query for searching in the notes containing the keywords the notes are likely to contain. '
               'Example: what do you know about my family? can have query as "family brother sister sibling mother father" '
               'The Message: {message}')


@dataclass
class Decision:
    retrieve: bool
    query: str          # what to search memory for: keywords, not the raw message
    reason: str         # a few words, for the trace
    input_tokens: int = 0
    output_tokens: int = 0


def should_retrieve(client, model: str, message: str) -> Decision:
    """One call to `model`, no tools. Never raises: on any failure, or a reply
    without usable JSON, retrieve with the message itself as the query."""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content":GATE_PROMPT.format(message=message)}]
        )
        text = response.choices[0].message.content or ""
        start = text.index("{")
        end = text.rindex("}") + 1
        data = json.loads(text[start:end])
        input_tokens, output_tokens = _tokens(response)
        decision = Decision(retrieve=bool(data.get("retrieve")), query=data.get("query") or message, reason=data.get("reason", ""),
                 input_tokens=input_tokens, output_tokens=output_tokens)

    except Exception as exc:
        return Decision(
            retrieve=True,
            query=message,
            reason=f"Gate failed open {exc}"
        )
    return decision