"""THE LOOP: reason, act, observe, repeat.
"""

from __future__ import annotations
import time
from junot.registry import ToolRegistry

LIMIT_NOTE = "Call limits are exhausted, do not call any tools now. Answer from what you currently have and say what's missing."
LIMIT_REPLY = "I ran out of steps before finishing. Try asking for less at once, or ask again."

def _tokens(response) -> tuple[int, int]:
    """(input, output) tokens of one response; (0, 0) when the provider sent no usage."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, 0
    return usage.prompt_tokens or 0, usage.completion_tokens or 0

def run_loop(
    client,
    model: str,
    messages: list[dict],
    tools: ToolRegistry,
    max_iterations: int = 10,
    observer = None
) -> str:
    """Run one agent turn and return the reply text.

    `messages` starts as [system, ...history, user] and is mutated in place:
    afterwards it holds every assistant message and tool result of the turn.
    """
    notify = observer or (lambda kind, event: None)
    for iteration in range(max_iterations):
        #Get response from the model
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools.schemas()
        )
        message = response.choices[0].message
        input_tokens, output_tokens = _tokens(response)
        notify("llm", {
            "iteration": iteration + 1,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "tool_calls": len(message.tool_calls or []),
            "final": False,
        })

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
            tool_name = call.function.name
            arguments = call.function.arguments
            started = time.perf_counter()
            output = tools.execute(tool_name, arguments)
            notify("tool", {
                "name": tool_name,
                "arguments": arguments,
                "output": output,
                "ok": not output.startswith("Error"),
                "duration_ms": int((time.perf_counter() - started) * 1000),
            })
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": output
            })


    try:
        response = client.chat.completions.create(
            model=model,
            messages= messages + [{"role": "user", "content": LIMIT_NOTE}],
            tools=tools.schemas(),
            tool_choice="none"
        )
    except Exception as e:
        return LIMIT_REPLY

    message = response.choices[0].message
    input_tokens, output_tokens = _tokens(response)
    notify("llm", {
        "iteration": max_iterations + 1,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tool_calls": 0,
        "final": True,
    })
    if not message.content:
        return LIMIT_REPLY

    messages.append({"role": "assistant", "content": message.content})
    return message.content