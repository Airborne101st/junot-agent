"""Step 4: the observer and the trace. These tests are the spec.

    uv run pytest tests/test_step04_observe.py -v

Your step 1 debug prints showed what a turn did, but only on the terminal,
only while you watched, and from inside the loop. This step makes the loop
announce what happens to whoever is listening, and writes it all to a file.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from junot.loop import run_loop
from junot.observe import Tracer, compose
from junot.registry import Tool, ToolRegistry
from tests.fakes import ScriptedClient, reply, tool_call

MODEL = "fake-model"
NOW = datetime(2026, 10, 18, 9, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def _start() -> list[dict]:
    return [{"role": "system", "content": "You are Junot."}, {"role": "user", "content": "go"}]


def _tools() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(Tool("echo", "Echo.", {"type": "object", "properties": {"text": {"type": "string"}}},
                           lambda text: f"echo: {text}"))
    registry.register(Tool("boom", "Fails.", {"type": "object", "properties": {}},
                           lambda: (_ for _ in ()).throw(RuntimeError("the disk is full"))))
    return registry


def _recorder():
    events: list[tuple[str, dict]] = []
    return events, lambda kind, event: events.append((kind, event))


def _lines(folder) -> list[dict]:
    path = folder / "2026-10-18.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ---- the loop announces what happens ----------------------------------------

def test_the_observer_is_optional():
    client = ScriptedClient([reply("Hi.")])
    assert run_loop(client, MODEL, _start(), _tools()) == "Hi."


def test_a_plain_reply_emits_one_llm_event_with_its_tokens():
    events, observer = _recorder()
    client = ScriptedClient([reply("Hi.", tokens=(120, 8))])
    run_loop(client, MODEL, _start(), _tools(), observer=observer)

    assert events == [("llm", {"iteration": 1, "input_tokens": 120, "output_tokens": 8,
                               "tool_calls": 0, "final": False})]


def test_a_tool_turn_emits_llm_tool_llm_in_order():
    events, observer = _recorder()
    client = ScriptedClient([
        reply(tool_calls=[tool_call("echo", {"text": "hi"})], tokens=(100, 20)),
        reply("Done.", tokens=(140, 5)),
    ])
    run_loop(client, MODEL, _start(), _tools(), observer=observer)

    assert [kind for kind, _ in events] == ["llm", "tool", "llm"]
    first, tool, second = (event for _, event in events)
    assert first["tool_calls"] == 1 and first["iteration"] == 1
    assert second["iteration"] == 2 and second["input_tokens"] == 140


def test_a_tool_event_says_what_ran_what_came_back_and_how_long_it_took():
    events, observer = _recorder()
    client = ScriptedClient([reply(tool_calls=[tool_call("echo", {"text": "hi"})]), reply("Done.")])
    run_loop(client, MODEL, _start(), _tools(), observer=observer)

    tool = events[1][1]
    assert tool["name"] == "echo"
    assert tool["arguments"] == json.dumps({"text": "hi"}), "the model's raw JSON string"
    assert tool["output"] == "echo: hi"
    assert tool["ok"] is True
    assert isinstance(tool["duration_ms"], int) and tool["duration_ms"] >= 0


def test_a_failed_tool_is_marked_not_ok():
    events, observer = _recorder()
    client = ScriptedClient([reply(tool_calls=[tool_call("boom", {})]), reply("It failed.")])
    run_loop(client, MODEL, _start(), _tools(), observer=observer)

    tool = events[1][1]
    assert tool["ok"] is False
    assert "the disk is full" in tool["output"]


def test_the_final_call_at_the_limit_is_marked_final():
    events, observer = _recorder()
    script = [reply(tool_calls=[tool_call("echo", {"text": str(i)}, f"c{i}")]) for i in range(2)]
    client = ScriptedClient(script + [reply("Partial.", tokens=(300, 12))])
    run_loop(client, MODEL, _start(), _tools(), max_iterations=2, observer=observer)

    llm = [event for kind, event in events if kind == "llm"]
    assert [e["final"] for e in llm] == [False, False, True]
    assert llm[-1]["input_tokens"] == 300


def test_a_response_without_usage_counts_zero_tokens():
    events, observer = _recorder()
    run_loop(ScriptedClient([reply("Hi.", tokens=None)]), MODEL, _start(), _tools(), observer=observer)
    assert events[0][1]["input_tokens"] == 0 and events[0][1]["output_tokens"] == 0


# ---- compose: many listeners, one turn --------------------------------------

def test_compose_calls_every_observer_in_order():
    seen = []
    both = compose(lambda k, e: seen.append(("a", k)), lambda k, e: seen.append(("b", k)))
    both("llm", {})
    assert seen == [("a", "llm"), ("b", "llm")]


def test_compose_skips_none():
    seen = []
    compose(None, lambda k, e: seen.append(k), None)("tool", {})
    assert seen == ["tool"]


def test_an_observer_that_raises_never_breaks_the_others_or_the_turn():
    """Watching a turn must never be able to break it. A full disk under the
    trace file is not a reason to lose the user's answer."""
    seen = []
    def broken(kind, event):
        raise OSError("disk full")
    observer = compose(broken, lambda k, e: seen.append(k))
    client = ScriptedClient([reply(tool_calls=[tool_call("echo", {"text": "hi"})]), reply("Done.")])

    assert run_loop(client, MODEL, _start(), _tools(), observer=observer) == "Done."
    assert seen == ["llm", "tool", "llm"]


# ---- the Tracer: every event, one JSON line each ----------------------------

def test_the_tracer_creates_its_folder_and_one_file_per_day(tmp_path):
    folder = tmp_path / "traces"
    tracer = Tracer(folder, clock=lambda: NOW)
    tracer.start_turn("hi")
    tracer.end_turn("Hello!")
    assert (folder / "2026-10-18.jsonl").exists()


def test_every_line_is_json_with_a_timestamp_turn_id_and_kind(tmp_path):
    tracer = Tracer(tmp_path, clock=lambda: NOW)
    tracer.start_turn("hi")
    tracer("llm", {"iteration": 1, "input_tokens": 10, "output_tokens": 2, "tool_calls": 0, "final": False})
    tracer.end_turn("Hello!")

    for line in _lines(tmp_path):
        assert line["ts"] == NOW.isoformat()
        assert line["turn_id"]
        assert line["kind"] in ("turn_start", "llm", "turn_end")
    assert _lines(tmp_path)[0]["user"] == "hi"


def test_each_turn_gets_its_own_id(tmp_path):
    tracer = Tracer(tmp_path, clock=lambda: NOW)
    first = tracer.start_turn("one")
    tracer.end_turn("1")
    second = tracer.start_turn("two")
    tracer.end_turn("2")

    assert first != second
    ids = [line["turn_id"] for line in _lines(tmp_path)]
    assert ids == [first, first, second, second]


def test_end_turn_totals_what_the_turn_used(tmp_path):
    tracer = Tracer(tmp_path, clock=lambda: NOW)
    tracer.start_turn("go")
    tracer("llm", {"iteration": 1, "input_tokens": 100, "output_tokens": 20, "tool_calls": 1, "final": False})
    tracer("tool", {"name": "echo", "arguments": "{}", "output": "x", "ok": True, "duration_ms": 3})
    tracer("llm", {"iteration": 2, "input_tokens": 140, "output_tokens": 5, "tool_calls": 0, "final": False})
    totals = tracer.end_turn("Done.")

    assert totals == {"reply": "Done.", "llm_calls": 2, "tool_calls": 1,
                      "input_tokens": 240, "output_tokens": 25}
    end = _lines(tmp_path)[-1]
    assert end["kind"] == "turn_end"
    assert {k: end[k] for k in totals} == totals


def test_totals_start_again_at_zero_each_turn(tmp_path):
    tracer = Tracer(tmp_path, clock=lambda: NOW)
    tracer.start_turn("one")
    tracer("llm", {"iteration": 1, "input_tokens": 100, "output_tokens": 20, "tool_calls": 0, "final": False})
    tracer.end_turn("1")
    tracer.start_turn("two")
    assert tracer.end_turn("2")["input_tokens"] == 0


def test_the_trace_keeps_tool_outputs_whole(tmp_path):
    """History cuts outputs to save tokens (step 3). The trace is for you,
    not the model, so it keeps everything."""
    tracer = Tracer(tmp_path, clock=lambda: NOW)
    tracer.start_turn("go")
    tracer("tool", {"name": "echo", "arguments": "{}", "output": "x" * 5000, "ok": True, "duration_ms": 1})
    tracer.end_turn("Done.")
    assert len(_lines(tmp_path)[1]["output"]) == 5000


def test_a_whole_turn_can_be_rebuilt_from_its_trace(tmp_path):
    tracer = Tracer(tmp_path, clock=lambda: NOW)
    client = ScriptedClient([
        reply(tool_calls=[tool_call("echo", {"text": "hi"})], tokens=(100, 20)),
        reply("Done.", tokens=(140, 5)),
    ])
    tracer.start_turn("say hi")
    answer = run_loop(client, MODEL, _start(), _tools(), observer=tracer)
    tracer.end_turn(answer)

    lines = _lines(tmp_path)
    assert [line["kind"] for line in lines] == ["turn_start", "llm", "tool", "llm", "turn_end"]
    assert lines[2]["output"] == "echo: hi"
    assert lines[-1]["reply"] == "Done."
    assert lines[-1]["input_tokens"] == 240
