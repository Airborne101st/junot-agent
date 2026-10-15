"""Step 2: the harness around the loop. These tests are the spec.

    uv run pytest tests/test_step02_harness.py -v

Two failures from step 1's experiments, and the cap the loop never had:
  - a tool that raises (Mars/Olympus) crashed the program;
  - a tool the model asked for but we don't have (KeyError) crashed it too;
  - `while True` had no upper bound on how many model calls a turn could make.
"""

from __future__ import annotations

import inspect
import json

from junot.loop import LIMIT_NOTE, LIMIT_REPLY, run_loop
from junot.registry import Tool, ToolRegistry
from junot.tools import build_registry
from tests.fakes import ScriptedClient, reply, tool_call

MODEL = "fake-model"
NO_ARGS = {"type": "object", "properties": {}}


def _start(question: str = "go") -> list[dict]:
    return [{"role": "system", "content": "You are Junot."}, {"role": "user", "content": question}]


def _echo() -> Tool:
    return Tool(name="echo", description="Echo the text back.",
                parameters={"type": "object", "properties": {"text": {"type": "string"}},
                            "required": ["text"]},
                fn=lambda text: f"echo: {text}")


def _boom() -> Tool:
    def fn():
        raise RuntimeError("the disk is full")
    return Tool(name="boom", description="Always fails.", parameters=NO_ARGS, fn=fn)


def _registry(*tools: Tool) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


# ---- the registry ------------------------------------------------------------

def test_to_api_is_the_openai_function_shape():
    assert _echo().to_api() == {
        "type": "function",
        "function": {"name": "echo", "description": "Echo the text back.",
                     "parameters": _echo().parameters},
    }


def test_schemas_keep_registration_order():
    registry = _registry(_echo(), _boom())
    assert [s["function"]["name"] for s in registry.schemas()] == ["echo", "boom"]


def test_get_returns_none_for_an_unknown_name():
    assert _registry(_echo()).get("nope") is None


def test_execute_parses_the_json_arguments_and_runs_the_tool():
    assert _registry(_echo()).execute("echo", json.dumps({"text": "hi"})) == "echo: hi"


# ---- errors as text: every failure is something the model can read -----------

def test_unknown_tool_is_an_error_string_not_a_keyerror():
    out = _registry(_echo()).execute("get_weather", "{}")
    assert out.startswith("Error")
    assert "get_weather" in out


def test_arguments_that_are_not_json_are_an_error_string():
    out = _registry(_echo()).execute("echo", "{text: hi")
    assert out.startswith("Error")
    assert "echo" in out


def test_arguments_the_function_does_not_accept_are_an_error_string():
    """The schema is a promise, not a guarantee: the model can send the wrong
    argument name, and fn(**args) then raises TypeError."""
    out = _registry(_echo()).execute("echo", json.dumps({"txt": "hi"}))
    assert out.startswith("Error")
    assert "echo" in out


def test_an_exception_inside_the_tool_is_an_error_string_with_its_message():
    out = _registry(_boom()).execute("boom", "{}")
    assert out.startswith("Error")
    assert "boom" in out
    assert "the disk is full" in out, "the model can only recover if it knows WHY"


def test_the_real_get_time_reports_a_bad_timezone_as_text():
    out = build_registry().execute("get_time", json.dumps({"timezone": "Mars/Olympus"}))
    assert out.startswith("Error")
    assert "Mars/Olympus" in out


def test_a_tool_error_goes_back_to_the_model_and_the_turn_goes_on():
    """Experiment 2, offline: the model sees the error and answers anyway."""
    client = ScriptedClient([
        reply(tool_calls=[tool_call("boom", {})]),
        reply("Sorry, that failed: the disk is full."),
    ])
    answer = run_loop(client, MODEL, _start(), _registry(_boom()))

    assert answer == "Sorry, that failed: the disk is full."
    result = client.calls[1]["messages"][-1]
    assert result["role"] == "tool"
    assert "the disk is full" in result["content"]


# ---- the iteration cap and the tools-off final answer --------------------------

def _runaway(n: int) -> list:
    """A model that asks for a tool every single time."""
    return [reply(tool_calls=[tool_call("echo", {"text": str(i)}, f"call_{i}")]) for i in range(n)]


def test_max_iterations_defaults_to_ten():
    assert inspect.signature(run_loop).parameters["max_iterations"].default == 10


def test_at_the_limit_one_last_call_with_tools_off_gives_the_reply():
    client = ScriptedClient(_runaway(3) + [reply("Here is what I found so far.")])
    messages = _start()
    answer = run_loop(client, MODEL, messages, _registry(_echo()), max_iterations=3)

    assert answer == "Here is what I found so far."
    assert len(client.calls) == 4, "three normal calls, then exactly one final call"
    final = client.calls[3]
    assert final["tool_choice"] == "none", "the final call must not be able to call tools"
    assert final["messages"][-1] == {"role": "user", "content": LIMIT_NOTE}
    assert all("tool_choice" not in c for c in client.calls[:3]), "normal calls leave tool_choice unset"


def test_the_limit_note_is_not_kept_in_history():
    """LIMIT_NOTE is an instruction for one call, not something the user said.
    The final answer is kept; the note is not."""
    client = ScriptedClient(_runaway(2) + [reply("Partial answer.")])
    messages = _start()
    run_loop(client, MODEL, messages, _registry(_echo()), max_iterations=2)

    assert client.calls[-1].get("tool_choice") == "none", "the reply must come from the final call"
    assert all(m.get("content") != LIMIT_NOTE for m in messages)
    assert messages[-1] == {"role": "assistant", "content": "Partial answer."}


def test_if_the_final_call_fails_the_reply_is_limit_reply():
    client = ScriptedClient(_runaway(2) + [RuntimeError("503 from the provider")])
    answer = run_loop(client, MODEL, _start(), _registry(_echo()), max_iterations=2)
    assert answer == LIMIT_REPLY


def test_if_the_final_call_says_nothing_the_reply_is_limit_reply():
    client = ScriptedClient(_runaway(2) + [reply(None)])
    answer = run_loop(client, MODEL, _start(), _registry(_echo()), max_iterations=2)
    assert answer == LIMIT_REPLY


def test_a_natural_end_inside_the_limit_makes_no_final_call():
    client = ScriptedClient(_runaway(2) + [reply("Done in three.")])
    answer = run_loop(client, MODEL, _start(), _registry(_echo()), max_iterations=3)
    assert answer == "Done in three."
    assert len(client.calls) == 3
