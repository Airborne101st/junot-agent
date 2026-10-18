"""Step 3: the session. These tests are the spec.

    uv run pytest tests/test_step03_session.py -v

Until now the REPL kept one ever-growing `messages` list: a system prompt
fixed at startup, and every raw tool result from every turn, re-sent forever.
The session rebuilds working memory for each turn instead.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from junot.loop import run_loop
from junot.registry import Tool, ToolRegistry
from junot.session import DEFAULT_SOUL, Session, tool_note
from tests.fakes import ScriptedClient, reply, tool_call

TOKYO = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 15, 14, 30, tzinfo=TOKYO)   # a Thursday


def _session(tmp_path, clock=lambda: NOW) -> Session:
    return Session(tmp_path, "fake-model", clock=clock)


def _tool_turn(output: str = "2026-10-15T14:30:00+09:00", call_id: str = "call_1") -> list[dict]:
    """The messages list as run_loop leaves it after one get_time call."""
    return [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "Time in Tokyo?"},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": call_id, "type": "function",
            "function": {"name": "get_time", "arguments": json.dumps({"timezone": "Asia/Tokyo"})}}]},
        {"role": "tool", "tool_call_id": call_id, "content": output},
        {"role": "assistant", "content": "It is 2:30pm in Tokyo."},
    ]


# ---- SOUL.md: the persona is a file, not code -------------------------------

def test_default_soul_is_written():
    assert DEFAULT_SOUL.strip(), "write who Junot is"


def test_first_use_creates_soul_md_from_the_default(tmp_path):
    assert not (tmp_path / "SOUL.md").exists()
    assert _session(tmp_path).soul() == DEFAULT_SOUL
    assert (tmp_path / "SOUL.md").read_text(encoding="utf-8") == DEFAULT_SOUL


def test_an_existing_soul_md_is_never_overwritten(tmp_path):
    (tmp_path / "SOUL.md").write_text("You are a pirate.", encoding="utf-8")
    assert _session(tmp_path).soul() == "You are a pirate."
    assert (tmp_path / "SOUL.md").read_text(encoding="utf-8") == "You are a pirate."


def test_editing_soul_md_changes_the_next_turn_without_a_restart(tmp_path):
    session = _session(tmp_path)
    session.build_system()
    (tmp_path / "SOUL.md").write_text("You are a pirate.", encoding="utf-8")
    assert "You are a pirate." in session.build_system()


# ---- the clock and the model name -------------------------------------------

def test_the_system_prompt_has_the_time_day_and_offset(tmp_path):
    system = _session(tmp_path).build_system()
    assert "2026-10-15T14:30+09:00" in system, "use now.isoformat(timespec='minutes')"
    assert "Thursday" in system


def test_the_clock_is_read_on_every_turn_not_once(tmp_path):
    times = iter([NOW, NOW + timedelta(hours=2)])
    session = _session(tmp_path, clock=lambda: next(times))
    assert "14:30" in session.build_system()
    assert "16:30" in session.build_system()


def test_the_system_prompt_names_the_model(tmp_path):
    assert "fake-model" in _session(tmp_path).build_system()


# ---- build_messages ----------------------------------------------------------

def test_messages_are_system_then_history_then_the_new_message(tmp_path):
    session = _session(tmp_path)
    session.record("hi", [{"role": "user", "content": "hi"},
                          {"role": "assistant", "content": "Hello!"}], "Hello!")
    messages = session.build_messages("And now?")

    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[0]["content"] == session.build_system()
    assert messages[-1] == {"role": "user", "content": "And now?"}


def test_build_messages_returns_a_new_list_each_time(tmp_path):
    """run_loop mutates the list it gets. That must not leak into history."""
    session = _session(tmp_path)
    messages = session.build_messages("hi")
    messages.append({"role": "tool", "tool_call_id": "x", "content": "junk"})
    assert [m["role"] for m in session.build_messages("hi")] == ["system", "user"]


# ---- record and tool_note: history keeps the gist, not the raw results ------

def test_a_turn_without_tools_is_recorded_as_is(tmp_path):
    session = _session(tmp_path)
    session.record("hi", [{"role": "user", "content": "hi"},
                          {"role": "assistant", "content": "Hello!"}], "Hello!")
    assert session.build_messages("x")[1:3] == [
        {"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello!"}]


def test_tool_note_is_empty_without_tools():
    assert tool_note([{"role": "user", "content": "hi"},
                      {"role": "assistant", "content": "Hello!"}]) == ""


def test_tool_note_names_the_tool_its_arguments_and_its_output():
    note = tool_note(_tool_turn())
    assert note.startswith("[tools used:")
    assert note.endswith("]")
    assert "get_time" in note
    assert "Asia/Tokyo" in note
    assert "2026-10-15T14:30:00+09:00" in note


def test_tool_note_keeps_errors_visible():
    """If a tool failed, the next turn should know it failed."""
    assert "Error running get_time" in tool_note(_tool_turn("Error running get_time: bad tz"))


def test_tool_note_cuts_long_outputs():
    note = tool_note(_tool_turn("x" * 5000))
    assert len(note) < 400, "a 5,000-character result would be re-sent on every later turn"


def test_tool_note_only_looks_at_the_latest_turn():
    """run_loop's list can start with old history; only this turn's tools count."""
    old = [{"role": "user", "content": "And London?"},
           {"role": "assistant", "content": None, "tool_calls": [{
               "id": "old_1", "type": "function",
               "function": {"name": "get_time", "arguments": '{"timezone": "Europe/London"}'}}]},
           {"role": "tool", "tool_call_id": "old_1", "content": "LONDON-TIME"},
           {"role": "assistant", "content": "It is 6:30am in London."}]
    note = tool_note(old + _tool_turn()[1:])
    assert note.count("get_time") == 1
    assert "Europe/London" not in note


def test_tool_note_lists_several_calls():
    turn = [
        {"role": "user", "content": "Tokyo and Paris?"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": "get_time", "arguments": '{"timezone": "Asia/Tokyo"}'}},
            {"id": "b", "type": "function", "function": {"name": "get_time", "arguments": '{"timezone": "Europe/Paris"}'}}]},
        {"role": "tool", "tool_call_id": "a", "content": "TOKYO-TIME"},
        {"role": "tool", "tool_call_id": "b", "content": "PARIS-TIME"},
        {"role": "assistant", "content": "Both done."},
    ]
    note = tool_note(turn)
    assert "Asia/Tokyo" in note and "Europe/Paris" in note
    assert "TOKYO-TIME" in note and "PARIS-TIME" in note


def test_record_stores_the_reply_with_its_note_and_no_tool_messages(tmp_path):
    session = _session(tmp_path)
    session.record("Time in Tokyo?", _tool_turn(), "It is 2:30pm in Tokyo.")
    history = session.build_messages("next")[1:-1]

    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[1]["content"].startswith("It is 2:30pm in Tokyo.")
    assert "[tools used:" in history[1]["content"]


# ---- the whole thing, across two turns --------------------------------------

def test_turn_two_sees_turn_one_as_text_not_as_raw_tool_messages(tmp_path):
    def fake_get_time(timezone: str) -> str:
        return "2026-10-15T14:30:00+09:00"
    tools = ToolRegistry()
    tools.register(Tool("get_time", "time", {"type": "object", "properties": {}}, fake_get_time))
    client = ScriptedClient([
        reply(tool_calls=[tool_call("get_time", {"timezone": "Asia/Tokyo"})]),
        reply("It is 2:30pm in Tokyo."),
        reply("You asked about Tokyo."),
    ])
    session = _session(tmp_path)

    for question in ["Time in Tokyo?", "What did I just ask?"]:
        messages = session.build_messages(question)
        answer = run_loop(client, "fake-model", messages, tools)
        session.record(question, messages, answer)

    seen_on_turn_two = client.calls[2]["messages"]
    assert [m["role"] for m in seen_on_turn_two] == ["system", "user", "assistant", "user"]
    assert "[tools used: get_time" in seen_on_turn_two[2]["content"]
