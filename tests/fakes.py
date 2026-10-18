"""A scripted fake model, so the harness can be tested offline with no key.

It returns objects shaped like the OpenAI SDK's ChatCompletion, with only the
fields the loop reads. Same idea as Waku's evals/helpers.py ScriptedClient.
"""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace


def tool_call(name: str, args: dict, call_id: str = "call_1", extra_content: dict | None = None):
    """One entry of message.tool_calls. Note: arguments is a JSON *string*.

    `extra_content` is what a provider adds beyond the OpenAI shape. Gemini 3
    puts {"google": {"thought_signature": "..."}} here on every tool call, and
    refuses the next request with a 400 if it is not sent back. Like the real
    SDK object, the attribute exists only when the provider sent it.
    """
    call = SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )
    if extra_content is not None:
        call.extra_content = extra_content
    return call


def reply(content: str | None = None, tool_calls: list | None = None,
          tokens: tuple[int, int] | None = (0, 0)):
    """One ChatCompletion: either text, or tool calls (content may be None).

    `tokens` is (prompt_tokens, completion_tokens). Pass None for a response
    with no usage at all, which some OpenAI-compatible providers send.
    """
    message = SimpleNamespace(role="assistant", content=content, tool_calls=tool_calls or None)
    usage = None
    if tokens is not None:
        usage = SimpleNamespace(prompt_tokens=tokens[0], completion_tokens=tokens[1],
                                total_tokens=tokens[0] + tokens[1])
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message,
                                 finish_reason="tool_calls" if tool_calls else "stop")],
        usage=usage,
    )


class ScriptedClient:
    """Plays back a fixed list of replies, and records every call it got.

    `calls[i]` is a deep copy of the kwargs of call i, so you can check what
    the model saw at that moment even though the loop keeps changing
    `messages` afterwards.
    """

    def __init__(self, script: list):
        self._script = list(script)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        if not self._script:
            raise AssertionError("the loop called the model more times than the test scripted")
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
