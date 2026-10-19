"""Step 5: long-term memory. These tests are the spec.

    uv run pytest tests/test_step05_memory.py -v

"Remember that my sister's birthday is 3 March." Quit. Start again. "When is
my sister's birthday?" Until now Junot can't do that: history lives in the
REPL's memory and dies with it.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from junot.loop import run_loop
from junot.memory import Memory, fts_query
from junot.tools import build_registry
from tests.fakes import ScriptedClient, reply, tool_call

NOW = datetime(2026, 10, 19, 9, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def _memory(tmp_path) -> Memory:
    return Memory(tmp_path / "state.db", clock=lambda: NOW)


# ---- fts_query: user text is not a valid search query -----------------------

def test_fts_query_quotes_every_word_and_joins_with_or():
    assert fts_query("what's up?") == '"what" OR "s" OR "up"'


def test_fts_query_of_no_words_is_empty():
    assert fts_query("?? !!") == ""
    assert fts_query("") == ""


# ---- the store ----------------------------------------------------------------

def test_the_database_file_is_created(tmp_path):
    memory = _memory(tmp_path)
    assert memory.path == tmp_path / "state.db", "keep the path: tools and the REPL report it"
    memory.close()
    assert (tmp_path / "state.db").exists()


def test_add_returns_increasing_ids(tmp_path):
    memory = _memory(tmp_path)
    first = memory.add("sister", "Her birthday is 3 March.")
    second = memory.add("work", "The team standup is at 10am.")
    assert second > first


def test_search_finds_a_fact_by_a_word_in_it_any_case(tmp_path):
    memory = _memory(tmp_path)
    memory.add("sister", "Her birthday is 3 March.")
    hits = memory.search("BIRTHDAY")
    assert [h["content"] for h in hits] == ["Her birthday is 3 March."]
    assert hits[0] == {"id": hits[0]["id"], "subject": "sister",
                       "content": "Her birthday is 3 March.", "created": NOW.isoformat()}


def test_search_finds_a_fact_by_its_subject(tmp_path):
    memory = _memory(tmp_path)
    memory.add("sister", "Her birthday is 3 March.")
    assert len(memory.search("sister")) == 1


def test_a_fact_survives_a_restart(tmp_path):
    """The whole point of this step: a new Memory on the same file, as after
    quitting and starting Junot again, still has the fact."""
    before = _memory(tmp_path)
    before.add("sister", "Her birthday is 3 March.")
    before.close()

    after = _memory(tmp_path)
    assert [h["content"] for h in after.search("birthday")] == ["Her birthday is 3 March."]


def test_the_best_match_comes_first(tmp_path):
    memory = _memory(tmp_path)
    memory.add("work", "The office birthday lunch is on Friday.")
    memory.add("sister", "My sister's birthday is 3 March.")
    hits = memory.search("sister birthday")
    assert hits[0]["subject"] == "sister", "a fact matching both words outranks one matching one"


def test_search_respects_the_limit(tmp_path):
    memory = _memory(tmp_path)
    for i in range(8):
        memory.add("note", f"Reminder number {i}.")
    assert len(memory.search("reminder", limit=3)) == 3


def test_no_match_is_an_empty_list(tmp_path):
    memory = _memory(tmp_path)
    memory.add("sister", "Her birthday is 3 March.")
    assert memory.search("volcano") == []


def test_punctuation_and_quotes_never_crash_the_search(tmp_path):
    """Raw text in MATCH is a syntax error: an apostrophe or a quote is
    enough. People type both all the time."""
    memory = _memory(tmp_path)
    memory.add("sister", "Her birthday is 3 March.")
    assert memory.search('what\'s my sister\'s "birthday"?')
    assert memory.search("?? !!") == []
    assert memory.search("") == []


def test_search_words_are_never_read_as_fts_operators(tmp_path):
    """AND, OR, NOT and NEAR mean something to FTS5. As words in a question
    they must just be words."""
    memory = _memory(tmp_path)
    memory.add("plans", "Do NOT book anything near the airport.")
    assert memory.search("NOT near AND OR")


def test_text_that_looks_like_sql_is_stored_as_text(tmp_path):
    """Values go in as ? parameters, never pasted into the SQL string."""
    memory = _memory(tmp_path)
    memory.add("odd", "Robert'); DROP TABLE facts; --")
    assert [h["content"] for h in memory.search("Robert")] == ["Robert'); DROP TABLE facts; --"]
    assert len(memory.all()) == 1


def test_all_returns_every_fact_oldest_first(tmp_path):
    memory = _memory(tmp_path)
    memory.add("a", "first")
    memory.add("b", "second")
    assert [f["content"] for f in memory.all()] == ["first", "second"]


def test_the_database_is_plain_sqlite_you_can_open(tmp_path):
    memory = _memory(tmp_path)
    memory.add("sister", "Her birthday is 3 March.")
    memory.close()
    rows = sqlite3.connect(tmp_path / "state.db").execute("SELECT content FROM facts").fetchall()
    assert rows == [("Her birthday is 3 March.",)]


# ---- the tools: how the model saves and finds facts -------------------------

def test_without_memory_the_registry_has_only_get_time():
    assert [s["function"]["name"] for s in build_registry().schemas()] == ["get_time"]


def test_with_memory_the_registry_adds_save_note_and_search_notes(tmp_path):
    names = [s["function"]["name"] for s in build_registry(_memory(tmp_path)).schemas()]
    assert names == ["get_time", "save_note", "search_notes"]


def test_the_memory_tools_say_when_to_use_them(tmp_path):
    for name in ("save_note", "search_notes"):
        assert len(build_registry(_memory(tmp_path)).get(name).description) > 40


def test_save_note_stores_the_fact_and_says_where(tmp_path):
    memory = _memory(tmp_path)
    out = build_registry(memory).execute(
        "save_note", json.dumps({"subject": "sister", "content": "Her birthday is 3 March."}))

    assert [f["content"] for f in memory.all()] == ["Her birthday is 3 March."]
    assert out.startswith("Saved note #")
    assert str(tmp_path / "state.db") in out, "say exactly where it was stored"


def test_save_note_refuses_an_empty_fact(tmp_path):
    memory = _memory(tmp_path)
    out = build_registry(memory).execute("save_note", json.dumps({"subject": "x", "content": "  "}))
    assert out.startswith("Error")
    assert memory.all() == []


def test_search_notes_returns_the_matching_facts(tmp_path):
    memory = _memory(tmp_path)
    memory.add("sister", "Her birthday is 3 March.")
    out = build_registry(memory).execute("search_notes", json.dumps({"query": "birthday"}))
    assert "Her birthday is 3 March." in out
    assert "sister" in out


def test_search_notes_says_plainly_when_nothing_matches(tmp_path):
    out = build_registry(_memory(tmp_path)).execute("search_notes", json.dumps({"query": "volcano"}))
    assert not out.startswith("Error"), "finding nothing is an answer, not a failure"
    assert "No notes" in out


def test_remember_restart_recall(tmp_path):
    """The step 5 demo, end to end, with a fresh Memory and registry for the
    second session as after a real restart."""
    first_session = _memory(tmp_path)
    client = ScriptedClient([
        reply(tool_calls=[tool_call("save_note", {"subject": "sister",
                                                  "content": "Her birthday is 3 March."})]),
        reply("Noted."),
    ])
    run_loop(client, "m", [{"role": "user", "content": "Remember my sister's birthday is 3 March."}],
             build_registry(first_session))
    first_session.close()

    second_session = _memory(tmp_path)
    client = ScriptedClient([
        reply(tool_calls=[tool_call("search_notes", {"query": "sister birthday"})]),
        reply("It is on 3 March."),
    ])
    messages = [{"role": "user", "content": "When is my sister's birthday?"}]
    run_loop(client, "m", messages, build_registry(second_session))

    assert "3 March" in messages[-2]["content"], "the search result the model read"
