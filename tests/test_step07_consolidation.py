"""Step 7: consolidation. These tests are the spec.

    uv run pytest tests/test_step07_consolidation.py -v

Junot learns notes from the conversation by itself, every few exchanges,
instead of only when it decides to call save_note.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from junot.consolidate import SUMMARIZER_PROMPT, maybe_consolidate
from junot.memory import Memory
from junot.observe import Tracer
from junot.session import Session
from tests.fakes import ScriptedClient, reply

NOW = datetime(2026, 10, 21, 18, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def _memory(tmp_path) -> Memory:
    return Memory(tmp_path / "state.db", clock=lambda: NOW)


def _chat(memory: Memory, n: int) -> None:
    for i in range(n):
        memory.log_exchange(f"user message {i}", f"assistant reply {i}")


def _summary(facts: list[dict], episode: str = "Talked about travel plans.", tokens=(400, 60)):
    return reply(json.dumps({"facts": facts, "episode": episode}), tokens=tokens)


FLIGHT = {"subject": "travel", "content": "The user is flying to Pune on Friday, October 23, 2026."}


# ---- the chat log and episodes in memory.py ---------------------------------

def test_an_exchange_is_logged_and_waits_to_be_consolidated(tmp_path):
    memory = _memory(tmp_path)
    first = memory.log_exchange("hi", "Hello!")
    memory.log_exchange("I fly to Pune on Friday", "Safe travels!")
    waiting = memory.unconsolidated()
    assert [w["user"] for w in waiting] == ["hi", "I fly to Pune on Friday"], "oldest first"
    assert waiting[0] == {"id": first, "created": NOW.isoformat(), "user": "hi", "assistant": "Hello!"}


def test_marked_exchanges_stop_waiting_and_the_rest_keep_waiting(tmp_path):
    memory = _memory(tmp_path)
    a = memory.log_exchange("one", "1")
    b = memory.log_exchange("two", "2")
    memory.log_exchange("three", "3")
    memory.mark_consolidated([a, b])
    assert [w["user"] for w in memory.unconsolidated()] == ["three"]


def test_waiting_exchanges_survive_a_restart(tmp_path):
    """Six exchanges can span two sessions: quit after three, come back."""
    before = _memory(tmp_path)
    _chat(before, 3)
    before.close()
    assert len(_memory(tmp_path).unconsolidated()) == 3


def test_episodes_are_stored_oldest_first(tmp_path):
    memory = _memory(tmp_path)
    memory.add_episode("2026-10-20", "Planned the trip.")
    memory.add_episode("2026-10-21", "Booked the flight.")
    assert [(e["date"], e["summary"]) for e in memory.episodes()] == [
        ("2026-10-20", "Planned the trip."), ("2026-10-21", "Booked the flight.")]


def test_a_database_from_step_5_gains_the_new_tables_and_keeps_its_facts(tmp_path):
    """Your real data/state.db has only `facts`. Opening it must not lose them."""
    path = tmp_path / "state.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE VIRTUAL TABLE facts USING fts5(subject, content, created UNINDEXED)")
    conn.execute("INSERT INTO facts VALUES ('brother', 'My brother is Swapnil.', '2026-10-19')")
    conn.commit()
    conn.close()

    memory = Memory(path, clock=lambda: NOW)
    assert [f["content"] for f in memory.all()] == ["My brother is Swapnil."]
    memory.log_exchange("hi", "Hello!")
    assert len(memory.unconsolidated()) == 1


# ---- the Session logs every exchange ------------------------------------------

def test_record_logs_the_exchange_with_its_tool_note(tmp_path):
    memory = _memory(tmp_path)
    session = Session(tmp_path, "m", clock=lambda: NOW, memory=memory)
    turn = [{"role": "user", "content": "time in Tokyo?"},
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "get_time", "arguments": '{"timezone": "Asia/Tokyo"}'}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "22:00"},
            {"role": "assistant", "content": "It is 10pm."}]
    session.record("time in Tokyo?", turn, "It is 10pm.")

    [logged] = memory.unconsolidated()
    assert logged["user"] == "time in Tokyo?"
    assert logged["assistant"].startswith("It is 10pm.")
    assert "[tools used: get_time" in logged["assistant"], "the same text history keeps"


def test_record_without_memory_still_works(tmp_path):
    session = Session(tmp_path, "m", clock=lambda: NOW)
    session.record("hi", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello!"}], "Hello!")
    assert len(session.history) == 2


# ---- maybe_consolidate --------------------------------------------------------

def test_the_prompt_asks_for_json_and_has_both_placeholders():
    assert "JSON" in SUMMARIZER_PROMPT
    assert "{exchanges}" in SUMMARIZER_PROMPT and "{known}" in SUMMARIZER_PROMPT


def test_not_due_means_no_call_and_nothing_changes(tmp_path):
    memory = _memory(tmp_path)
    _chat(memory, 5)
    client = ScriptedClient([])
    assert maybe_consolidate(client, "small", memory, every=6) is None
    assert client.calls == [], "five exchanges, every=6: no model call at all"
    assert len(memory.unconsolidated()) == 5


def test_when_due_one_call_stores_facts_and_an_episode(tmp_path):
    memory = _memory(tmp_path)
    _chat(memory, 6)
    client = ScriptedClient([_summary([FLIGHT])])
    result = maybe_consolidate(client, "the-small-model", memory, every=6)

    assert len(client.calls) == 1
    assert client.calls[0]["model"] == "the-small-model"
    assert "tools" not in client.calls[0]
    assert [f["content"] for f in memory.all()] == [FLIGHT["content"]]
    assert memory.episodes()[0] == {"id": memory.episodes()[0]["id"], "date": "2026-10-21",
                                    "summary": "Talked about travel plans."}
    assert memory.unconsolidated() == [], "all six are done"
    assert result.facts == [FLIGHT]
    assert result.episode == "Talked about travel plans."
    assert (result.input_tokens, result.output_tokens) == (400, 60)


def test_the_prompt_holds_the_exchanges_and_the_facts_already_known(tmp_path):
    memory = _memory(tmp_path)
    memory.add("brother", "My brother Swapnil's birthday is June 20.")
    memory.log_exchange("I fly to Pune on Friday", "Safe travels, General!")
    client = ScriptedClient([_summary([])])
    maybe_consolidate(client, "small", memory, every=1)

    prompt = client.calls[0]["messages"][-1]["content"]
    assert "I fly to Pune on Friday" in prompt
    assert "Safe travels, General!" in prompt
    assert "My brother Swapnil's birthday is June 20." in prompt, "so it doesn't propose it again"


def test_json_in_a_code_fence_is_still_read(tmp_path):
    memory = _memory(tmp_path)
    _chat(memory, 1)
    fenced = "Here you go:\n```json\n" + json.dumps({"facts": [FLIGHT], "episode": "x"}) + "\n```"
    maybe_consolidate(ScriptedClient([reply(fenced)]), "small", memory, every=1)
    assert len(memory.all()) == 1


def test_a_fact_already_stored_is_not_stored_again(tmp_path):
    """You said "remember" and save_note stored it. The summarizer reads the
    same exchange and proposes it again. Compare ignoring case and spaces."""
    memory = _memory(tmp_path)
    memory.add("travel", FLIGHT["content"])
    _chat(memory, 1)
    shouty = {"subject": "travel", "content": "  " + FLIGHT["content"].upper() + " "}
    result = maybe_consolidate(ScriptedClient([_summary([shouty, FLIGHT])]), "small", memory, every=1)
    assert len(memory.all()) == 1
    assert result.facts == []


def test_a_fact_repeated_in_one_batch_is_stored_once(tmp_path):
    memory = _memory(tmp_path)
    _chat(memory, 1)
    maybe_consolidate(ScriptedClient([_summary([FLIGHT, dict(FLIGHT)])]), "small", memory, every=1)
    assert len(memory.all()) == 1


def test_a_fact_with_no_content_is_skipped(tmp_path):
    memory = _memory(tmp_path)
    _chat(memory, 1)
    junk = [{"subject": "x", "content": "  "}, {"subject": "y"}, "not even a dict"]
    maybe_consolidate(ScriptedClient([_summary(junk + [FLIGHT])]), "small", memory, every=1)
    assert [f["content"] for f in memory.all()] == [FLIGHT["content"]]


def test_an_empty_episode_stores_no_episode(tmp_path):
    memory = _memory(tmp_path)
    _chat(memory, 1)
    maybe_consolidate(ScriptedClient([_summary([FLIGHT], episode="")]), "small", memory, every=1)
    assert memory.episodes() == []


# ---- nothing is lost when it fails --------------------------------------------

def test_a_failed_call_keeps_every_exchange_for_next_time(tmp_path):
    memory = _memory(tmp_path)
    _chat(memory, 6)
    assert maybe_consolidate(ScriptedClient([RuntimeError("503")]), "small", memory, every=6) is None
    assert len(memory.unconsolidated()) == 6
    assert memory.all() == [] and memory.episodes() == []


def test_a_reply_without_json_keeps_every_exchange(tmp_path):
    memory = _memory(tmp_path)
    _chat(memory, 6)
    assert maybe_consolidate(ScriptedClient([reply("Sorry, I can't.")]), "small", memory, every=6) is None
    assert len(memory.unconsolidated()) == 6


def test_after_a_failure_the_next_batch_tries_again(tmp_path):
    memory = _memory(tmp_path)
    _chat(memory, 6)
    client = ScriptedClient([RuntimeError("503"), _summary([FLIGHT])])
    maybe_consolidate(client, "small", memory, every=6)
    maybe_consolidate(client, "small", memory, every=6)
    assert len(memory.all()) == 1 and memory.unconsolidated() == []


# ---- it reports what it did ----------------------------------------------------

def test_success_is_reported_with_what_was_learned(tmp_path):
    memory = _memory(tmp_path)
    _chat(memory, 2)
    events = []
    maybe_consolidate(ScriptedClient([_summary([FLIGHT])]), "small", memory, every=2,
                      observer=lambda kind, event: events.append((kind, event)))
    assert events == [("consolidation", {
        "exchanges": 2, "facts": [FLIGHT["content"]], "episode": "Talked about travel plans.",
        "input_tokens": 400, "output_tokens": 60})]


def test_a_failure_is_reported_with_its_error(tmp_path):
    memory = _memory(tmp_path)
    _chat(memory, 2)
    events = []
    maybe_consolidate(ScriptedClient([RuntimeError("503 from the provider")]), "small", memory, every=2,
                      observer=lambda kind, event: events.append((kind, event)))
    [(kind, event)] = events
    assert kind == "consolidation"
    assert event["exchanges"] == 2 and event["facts"] == []
    assert "503 from the provider" in event["error"], "a fallback you can't see hides a broken part"


def test_not_due_reports_nothing(tmp_path):
    events = []
    maybe_consolidate(ScriptedClient([]), "small", _memory(tmp_path), every=6,
                      observer=lambda kind, event: events.append(kind))
    assert events == []


def test_the_summarizers_tokens_count_in_the_turns_total(tmp_path):
    tracer = Tracer(tmp_path / "traces", clock=lambda: NOW)
    tracer.start_turn("x")
    tracer("consolidation", {"exchanges": 6, "facts": [], "episode": "", "input_tokens": 400, "output_tokens": 60})
    totals = tracer.end_turn("ok")
    assert (totals["input_tokens"], totals["output_tokens"], totals["llm_calls"]) == (400, 60, 0)


# ---- the whole idea -------------------------------------------------------------

def test_a_fact_said_in_passing_is_recalled_later_without_save_note(tmp_path):
    """Step 7's "done when": nobody said "remember", nobody called save_note."""
    memory = _memory(tmp_path)
    session = Session(tmp_path, "m", clock=lambda: NOW, memory=memory)
    session.record("I'm flying to Pune on Friday.", [{"role": "assistant", "content": "Safe travels!"}],
                   "Safe travels!")
    maybe_consolidate(ScriptedClient([_summary([FLIGHT])]), "small", memory, every=1)

    later = Session(tmp_path, "m", clock=lambda: NOW, memory=memory)
    assert "Pune" in later.build_messages("Where am I flying on Friday?")[0]["content"]
