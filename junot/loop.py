"""THE LOOP: reason, act, observe, repeat.

YOUR CODE (step 1). See docs/steps/01-the-loop.md.
"""

from __future__ import annotations
import json
from collections.abc import Callable


def run_loop(
    client,
    model: str,
    messages: list[dict],
    tool_schemas: list[dict],
    tool_fns: dict[str, Callable[..., str]],
) -> str:
    """Run one agent turn and return the reply text.

    `messages` starts as [system, ...history, user] and is mutated in place:
    afterwards it holds every assistant message and tool result of the turn.
    """
    while True:
        #Get response from the model
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tool_schemas
        )
        message = response.choices[0].message

        # If no tool calls, append the assistant message and return its content
        if not message.tool_calls:
            messages.append({"role": "assistant", "content": message.content})
            return message.content

        # Append the assistant message with tool calls
        tool_calls_list = []
        for call in message.tool_calls:
            tool_call_dict = {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                }
            }
            if getattr(call, "extra_content", None):
                tool_call_dict["extra_content"] = call.extra_content
            tool_calls_list.append(tool_call_dict)


        message_dict = {
            "role": "assistant",
            "content": message.content,
            "tool_calls": tool_calls_list
        }
        messages.append(message_dict)


        #Call the tool and append in the messages
        for call in message.tool_calls:
            fn = tool_fns[call.function.name]
            args = json.loads(call.function.arguments)
            output = fn(**args)
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": output
            })


