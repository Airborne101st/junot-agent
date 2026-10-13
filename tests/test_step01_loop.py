"""Step 1: the bare loop. These tests are the spec; make them pass.

    uv run pytest tests/test_step01_loop.py -v
"""

from __future__ import annotations

import json

from junot.loop import run_loop
from junot.tools import GET_TIME_SCHEMA, TOOL_FNS, get_time
from tests.fakes import ScriptedClient, reply, tool_call

MODEL = "fake-model"
SYSTEM = {"role": "system", "content": "You are Junot."}


def _start(question: str = "What time is it in Tokyo?") -> list[dict]:
    return [dict(SYSTEM), {"role": "user", "content": question}]


def _recording_fns(log: list):
    def fake_get_time(timezone: str) -> str:
        log.append(timezone)
        return f"2026-10-11T09:00:00 in {timezone}"
    return {"get_time": fake_get_time}


# ---- the tool itself ---------------------------------------------------------

def test_schema_is_in_openai_function_shape():
    assert GET_TIME_SCHEMA["type"] == "function"
    fn = GET_TIME_SCHEMA["function"]
    assert fn["name"] == "get_time"
    assert fn["description"], "the model reads the description: write one"
    params = fn["parameters"]
    assert params["type"] == "object"
    assert "timezone" in params["properties"]
    assert params["required"] == ["timezone"]


def test_get_time_returns_local_time_with_offset():
    assert "+09:00" in get_time("Asia/Tokyo")


def test_tool_fns_maps_name_to_function():
    assert TOOL_FNS["get_time"] is get_time


# ---- exit 1: no tool calls means the model is talking to the human -----------

def test_plain_reply_returns_after_one_call():
    client = ScriptedClient([reply("Hello!")])
    assert run_loop(client, MODEL, _start("hi"), [GET_TIME_SCHEMA], TOOL_FNS) == "Hello!"
    assert len(client.calls) == 1


def test_every_call_sends_model_messages_and_tools():
    client = ScriptedClient([reply("Hello!")])
    run_loop(client, MODEL, _start("hi"), [GET_TIME_SCHEMA], TOOL_FNS)
    call = client.calls[0]
    assert call["model"] == MODEL
    assert call["tools"] == [GET_TIME_SCHEMA]
    assert call["messages"][0] == SYSTEM


# ---- act and observe ---------------------------------------------------------

def test_tool_call_runs_the_tool_and_feeds_the_result_back():
    seen: list[str] = []
    client = ScriptedClient([
        reply(tool_calls=[tool_call("get_time", {"timezone": "Asia/Tokyo"})]),
        reply("It is 9am in Tokyo."),
    ])
    answer = run_loop(client, MODEL, _start(), [GET_TIME_SCHEMA], _recording_fns(seen))

    assert answer == "It is 9am in Tokyo."
    assert seen == ["Asia/Tokyo"], "the tool must run with the model's arguments, parsed from JSON"
    assert len(client.calls) == 2

    # What the model saw on its second call: its own request, then the result.
    second = client.calls[1]["messages"]
    assistant, result = second[-2], second[-1]
    assert assistant["role"] == "assistant"
    assert result == {"role": "tool", "tool_call_id": "call_1",
                      "content": "2026-10-11T09:00:00 in Asia/Tokyo"}


def test_assistant_tool_request_is_kept_in_wire_shape():
    """The API rejects a tool result whose tool_call_id it has not seen in the
    assistant message before it, so that message must go back exactly."""
    client = ScriptedClient([
        reply(tool_calls=[tool_call("get_time", {"timezone": "UTC"}, "call_xyz")]),
        reply("Done."),
    ])
    run_loop(client, MODEL, _start(), [GET_TIME_SCHEMA], _recording_fns([]))

    assistant = client.calls[1]["messages"][-2]
    assert isinstance(assistant, dict), "append plain dicts, not SDK objects"
    assert assistant["tool_calls"] == [{
        "id": "call_xyz",
        "type": "function",
        "function": {"name": "get_time", "arguments": json.dumps({"timezone": "UTC"})},
    }]


def test_provider_extras_on_a_tool_call_are_sent_back():
    """Gemini 3 found this one live: a 400 "Function call is missing a
    thought_signature". The loop rebuilt each tool call from id, type and
    function only, and dropped the signature Gemini attached in extra_content."""
    signature = {"google": {"thought_signature": "sig-abc"}}
    client = ScriptedClient([
        reply(tool_calls=[tool_call("get_time", {"timezone": "UTC"}, "call_1", signature)]),
        reply("Noon."),
    ])
    run_loop(client, MODEL, _start(), [GET_TIME_SCHEMA], _recording_fns([]))

    sent_back = client.calls[1]["messages"][-2]["tool_calls"][0]
    assert sent_back["extra_content"] == signature


def test_two_tool_calls_in_one_reply_both_run_in_order():
    seen: list[str] = []
    client = ScriptedClient([
        reply(tool_calls=[tool_call("get_time", {"timezone": "Asia/Tokyo"}, "call_1"),
                          tool_call("get_time", {"timezone": "Europe/Paris"}, "call_2")]),
        reply("Tokyo is 9am, Paris is 2am."),
    ])
    run_loop(client, MODEL, _start("Tokyo and Paris?"), [GET_TIME_SCHEMA], _recording_fns(seen))

    assert seen == ["Asia/Tokyo", "Europe/Paris"]
    results = [m for m in client.calls[1]["messages"] if m["role"] == "tool"]
    assert [r["tool_call_id"] for r in results] == ["call_1", "call_2"]


def test_messages_hold_the_whole_turn_afterwards():
    """Like Waku, `messages` is mutated in place: after the call it is the turn's
    full working memory, which is what a later step will trace."""
    messages = _start()
    client = ScriptedClient([
        reply(tool_calls=[tool_call("get_time", {"timezone": "UTC"})]),
        reply("Noon."),
    ])
    run_loop(client, MODEL, messages, [GET_TIME_SCHEMA], _recording_fns([]))

    assert [m["role"] for m in messages] == ["system", "user", "assistant", "tool", "assistant"]
    assert messages[-1] == {"role": "assistant", "content": "Noon."}
