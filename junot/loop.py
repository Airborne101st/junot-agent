"""THE LOOP: reason, act, observe, repeat.
"""

from __future__ import annotations
from junot.registry import ToolRegistry

LIMIT_NOTE = "Call limits are exhausted, do not call any tools now. Answer from what you currently have and say what's missing."
LIMIT_REPLY = "I ran out of steps before finishing. Try asking for less at once, or ask again."


def run_loop(
    client,
    model: str,
    messages: list[dict],
    tools: ToolRegistry,
    max_iterations: int = 10,
) -> str:
    """Run one agent turn and return the reply text.

    `messages` starts as [system, ...history, user] and is mutated in place:
    afterwards it holds every assistant message and tool result of the turn.
    """
    for iteration in range(max_iterations):
        #Get response from the model
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools.schemas()
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
            tool_name = call.function.name
            arguments = call.function.arguments
            output = tools.execute(tool_name, arguments)
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
    if not message.content:
        return LIMIT_REPLY

    messages.append({"role": "assistant", "content": message.content})
    return message.content