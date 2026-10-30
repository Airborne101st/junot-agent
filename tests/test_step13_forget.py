"""Step 13: forget and correct. These tests are the spec.

    uv run pytest tests/test_step13_forget.py -v

Step 5's review: asked to forget, Junot promised to "disregard the record in
all future affairs". Nothing stored that promise; the note stayed and came
back next session. Step 10's eval scored it 1/5 on every run.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from junot.consolidate import SUMMARIZER_PROMPT
from junot.loop import run_loop
from junot.memory import Memory
from junot.session import Session
from junot.gate import Decision
from junot.tools import build_registry
from tests.fakes import ScriptedClient, reply, tool_call

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def _memory(tmp_path) -> Memory:
    memory = Memory(tmp_path / "state.db", clock=lambda: NOW)
    memory.add("brother", "The user's brother is named Swapnil.")
    memory.add("passport", "The user's passport expires on Wednesday, March 3, 2027.")
    return memory


# ---- memory -----------------------------------------------------------------------

def test_forget_really_deletes_the_row(tmp_path):
    memory = _memory(tmp_path)
    forgotten = memory.forget(1)
    assert forgotten["content"] == "The user's brother is named Swapnil."
    assert memory.get(1) is None
    assert memory.search("Swapnil") == []
    rows = sqlite3.connect(tmp_path / "state.db").execute("SELECT content FROM facts").fetchall()
    assert rows == [("The user's passport expires on Wednesday, March 3, 2027.",)], "gone from the file itself"


def test_forgetting_survives_a_restart(tmp_path):
    _memory(tmp_path).forget(1)
    assert Memory(tmp_path / "state.db").search("brother Swapnil") == []


def test_forgetting_a_note_that_doesnt_exist_changes_nothing(tmp_path):
    memory = _memory(tmp_path)
    assert memory.forget(99) is None
    assert len(memory.all()) == 2


def test_correct_replaces_the_content_and_keeps_the_id(tmp_path):
    memory = _memory(tmp_path)
    before = memory.correct(2, "The user's passport expires on Friday, March 3, 2028.")
    assert before["content"].endswith("2027.")
    assert memory.get(2)["content"] == "The user's passport expires on Friday, March 3, 2028."
    assert memory.get(2)["subject"] == "passport"
    assert [h["id"] for h in memory.search("passport 2028")] == [2], "the search index follows the change"


# ---- the tools ------------------------------------------------------------------------

def test_forget_note_deletes_and_says_exactly_what(tmp_path):
    memory = _memory(tmp_path)
    out = build_registry(memory).execute("forget_note", json.dumps({"note_id": 1}))
    assert "Swapnil" in out and "#1" in out and "can't be recovered" in out
    assert memory.get(1) is None


def test_ids_written_as_text_or_with_a_hash_work_too(tmp_path):
    memory = _memory(tmp_path)
    registry = build_registry(memory)
    assert not registry.execute("forget_note", json.dumps({"note_id": "#1"})).startswith("Error")
    assert not registry.execute("forget_note", json.dumps({"note_id": "2"})).startswith("Error")
    assert memory.all() == []


def test_forgetting_an_unknown_note_is_an_error_the_model_can_read(tmp_path):
    out = build_registry(_memory(tmp_path)).execute("forget_note", json.dumps({"note_id": 42}))
    assert out.startswith("Error") and "42" in out


def test_correct_note_shows_before_and_after(tmp_path):
    memory = _memory(tmp_path)
    out = build_registry(memory).execute(
        "correct_note", json.dumps({"note_id": 2, "content": "The user's passport expires on Friday, March 3, 2028."}))
    assert "2027" in out and "2028" in out
    assert memory.get(2)["content"].endswith("2028.")


def test_correcting_to_nothing_is_refused(tmp_path):
    memory = _memory(tmp_path)
    out = build_registry(memory).execute("correct_note", json.dumps({"note_id": 2, "content": "  "}))
    assert out.startswith("Error") and memory.get(2)["content"].endswith("2027.")


def test_the_descriptions_say_when_and_warn_against_empty_promises(tmp_path):
    registry = build_registry(_memory(tmp_path))
    forget = registry.get("forget_note").description
    assert "ONLY" in forget and "Never say" in forget
    assert "correct" in registry.get("correct_note").description.lower()


# ---- recalled notes carry their id -------------------------------------------------------

def test_recalled_notes_show_their_id_so_they_can_be_forgotten(tmp_path):
    memory = _memory(tmp_path)
    session = Session(tmp_path, "m", clock=lambda: NOW, memory=memory,
                      gate=lambda message: Decision(True, "brother", "test"))
    assert "#1 [brother] The user's brother is named Swapnil." in session.build_messages("forget my brother")[0]["content"]


def test_forget_in_one_turn_without_searching(tmp_path):
    """The note is already in the prompt with its id, so one tool call does it."""
    memory = _memory(tmp_path)
    session = Session(tmp_path, "m", clock=lambda: NOW, memory=memory,
                      gate=lambda message: Decision(True, "brother name", "test"))
    client = ScriptedClient([reply(tool_calls=[tool_call("forget_note", {"note_id": 1})]),
                             reply("Done: I deleted note #1 about your brother's name.")])
    run_loop(client, "m", session.build_messages("Forget my brother's name."), build_registry(memory))
    assert memory.get(1) is None and memory.get(2) is not None


# ---- and it isn't learned back ---------------------------------------------------------------

def test_the_summarizer_is_told_not_to_relearn_what_was_forgotten():
    """Consolidation reads the same exchanges: "my brother Swapnil..." earlier,
    "forget my brother's name" now. Without this rule it could store it again."""
    assert "forget" in SUMMARIZER_PROMPT.lower()
