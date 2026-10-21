"""Step 6: the retrieval gate. These tests are the spec.

    uv run pytest tests/test_step06_gate.py -v

Two parts: should_retrieve() makes the decision, and the Session uses it to
put the matching notes into the system prompt before the main model runs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from junot.gate import GATE_PROMPT, Decision, should_retrieve
from junot.loop import run_loop
from junot.memory import Memory
from junot.observe import Tracer
from junot.session import Session
from junot.tools import build_registry
from tests.fakes import ScriptedClient, reply

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))


# ---- should_retrieve: one narrow decision ------------------------------------

def test_the_gate_prompt_asks_for_json_and_takes_the_message():
    assert "JSON" in GATE_PROMPT
    assert "{message}" in GATE_PROMPT


def test_a_yes_comes_back_with_the_gates_own_keywords():
    client = ScriptedClient([reply('{"retrieve": true, "query": "brother sister", "reason": "asks about family"}')])
    decision = should_retrieve(client, "small", "Do I have a sibling?")
    assert decision.retrieve is True
    assert decision.query == "brother sister"
    assert decision.reason == "asks about family"


def test_a_no_comes_back_as_no():
    client = ScriptedClient([reply('{"retrieve": false, "query": "", "reason": "arithmetic"}')])
    assert should_retrieve(client, "small", "What is 17 times 4?").retrieve is False


def test_it_is_one_call_to_the_small_model_with_no_tools():
    client = ScriptedClient([reply('{"retrieve": false, "query": "", "reason": "x"}')])
    should_retrieve(client, "the-small-model", "hi")
    assert len(client.calls) == 1
    assert client.calls[0]["model"] == "the-small-model"
    assert "tools" not in client.calls[0]


def test_the_users_message_is_in_the_prompt():
    client = ScriptedClient([reply('{"retrieve": false, "query": "", "reason": "x"}')])
    should_retrieve(client, "small", "When is Swapnil's birthday?")
    sent = " ".join(m["content"] for m in client.calls[0]["messages"])
    assert "When is Swapnil's birthday?" in sent


def test_json_inside_a_code_fence_or_prose_is_still_read():
    """Small models love to wrap JSON in ```json fences or add a sentence."""
    client = ScriptedClient([reply('Sure!\n```json\n{"retrieve": true, "query": "birthday", "reason": "dates"}\n```')])
    decision = should_retrieve(client, "small", "When is my birthday?")
    assert decision.retrieve is True and decision.query == "birthday"


def test_the_gates_tokens_are_kept():
    client = ScriptedClient([reply('{"retrieve": false, "query": "", "reason": "x"}', tokens=(90, 15))])
    decision = should_retrieve(client, "small", "hi")
    assert (decision.input_tokens, decision.output_tokens) == (90, 15)


# ---- failing open ------------------------------------------------------------

def test_if_the_call_fails_it_retrieves_with_the_message():
    client = ScriptedClient([RuntimeError("503 from the provider")])
    decision = should_retrieve(client, "small", "When is my brother's birthday?")
    assert decision.retrieve is True
    assert decision.query == "When is my brother's birthday?"
    assert "fail" in decision.reason.lower()


def test_a_reply_with_no_json_fails_open():
    client = ScriptedClient([reply("I think you should look it up.")])
    decision = should_retrieve(client, "small", "Where does my brother live?")
    assert decision.retrieve is True and decision.query == "Where does my brother live?"


def test_broken_json_fails_open():
    client = ScriptedClient([reply('{"retrieve": true, "query": ')])
    assert should_retrieve(client, "small", "my plans?").retrieve is True


def test_an_empty_reply_fails_open():
    client = ScriptedClient([reply(None)])
    assert should_retrieve(client, "small", "my plans?").retrieve is True


def test_a_yes_without_keywords_searches_the_message():
    client = ScriptedClient([reply('{"retrieve": true, "query": "", "reason": "personal"}')])
    assert should_retrieve(client, "small", "my plans?").query == "my plans?"


# ---- the Session: recalled notes go into the system prompt ------------------

def _memory(tmp_path) -> Memory:
    memory = Memory(tmp_path / "state.db", clock=lambda: NOW)
    memory.add("brother", "My brother Swapnil's birthday is June 20.")
    memory.add("meeting", "Design review on Tuesday, October 20, 2026 at 12:15 PM.")
    return memory


def _gate(retrieve: bool, query: str = "", log: list | None = None):
    def gate(message: str) -> Decision:
        if log is not None:
            log.append(message)
        return Decision(retrieve, query, "test", input_tokens=50, output_tokens=10)
    return gate


def _session(tmp_path, **kwargs) -> Session:
    return Session(tmp_path, "fake-model", clock=lambda: NOW, **kwargs)


def test_without_memory_nothing_changes(tmp_path):
    asked = []
    session = _session(tmp_path, gate=_gate(True, "brother", asked))
    assert "Swapnil" not in session.build_messages("When is my brother's birthday?")[0]["content"]
    assert asked == [], "no memory, so nothing to gate"


def test_a_yes_puts_the_matching_notes_in_the_system_prompt(tmp_path):
    session = _session(tmp_path, memory=_memory(tmp_path), gate=_gate(True, "brother birthday"))
    system = session.build_messages("When is my brother's birthday?")[0]["content"]
    assert "My brother Swapnil's birthday is June 20." in system
    assert "Design review" not in system, "only what matched"


def test_the_prompt_says_the_notes_were_already_searched_and_for_what(tmp_path):
    """Measured live: without this, the main model called search_notes twice
    more for notes already in its prompt, and "do I have a sibling?" cost
    2,463 tokens instead of 742."""
    session = _session(tmp_path, memory=_memory(tmp_path), gate=_gate(True, "brother birthday"))
    system = session.build_messages("When is my brother's birthday?")[0]["content"]
    assert "brother birthday" in system, "name the query that was searched"
    assert "search_notes" in system, "say when searching again is (and isn't) worth it"


def test_a_no_searches_nothing(tmp_path):
    asked = []
    session = _session(tmp_path, memory=_memory(tmp_path), gate=_gate(False, log=asked))
    system = session.build_messages("What is 17 times 4?")[0]["content"]
    assert asked == ["What is 17 times 4?"], "the gate is asked once, with the message"
    assert "Swapnil" not in system and "Design review" not in system


def test_the_gates_keywords_are_searched_not_the_raw_message(tmp_path):
    """"sibling" is in no note. The gate's "brother" is."""
    session = _session(tmp_path, memory=_memory(tmp_path), gate=_gate(True, "brother"))
    assert "Swapnil" in session.build_messages("Do I have a sibling?")[0]["content"]


def test_no_hits_means_no_memory_section(tmp_path):
    plain = _session(tmp_path).build_system()
    session = _session(tmp_path, memory=_memory(tmp_path), gate=_gate(True, "volcano"))
    assert session.build_messages("Any volcano trips?")[0]["content"] == plain


def test_at_most_five_notes_are_recalled(tmp_path):
    memory = Memory(tmp_path / "state.db", clock=lambda: NOW)
    for i in range(9):
        memory.add("trip", f"Trip number {i} is planned.")
    session = _session(tmp_path, memory=memory, gate=_gate(True, "trip"))
    system = session.build_messages("my trips?")[0]["content"]
    assert sum(f"Trip number {i} " in system for i in range(9)) == 5


def test_without_a_gate_memory_is_searched_with_the_message(tmp_path):
    """No gate is the same as a gate that always says yes: fail open."""
    session = _session(tmp_path, memory=_memory(tmp_path))
    assert "Swapnil" in session.build_messages("brother")[0]["content"]


def test_the_decision_is_reported_to_the_observer(tmp_path):
    events = []
    session = _session(tmp_path, memory=_memory(tmp_path), gate=_gate(True, "brother"),
                       observer=lambda kind, event: events.append((kind, event)))
    session.build_messages("Do I have a sibling?")
    assert events == [("gate", {"retrieve": True, "query": "brother", "reason": "test", "hits": 1,
                                "input_tokens": 50, "output_tokens": 10})]


def test_a_skip_is_reported_with_zero_hits(tmp_path):
    events = []
    session = _session(tmp_path, memory=_memory(tmp_path), gate=_gate(False),
                       observer=lambda kind, event: events.append((kind, event)))
    session.build_messages("hi")
    assert events[0][1]["retrieve"] is False and events[0][1]["hits"] == 0


def test_the_gates_tokens_count_in_the_turns_total(tmp_path):
    tracer = Tracer(tmp_path / "traces", clock=lambda: NOW)
    tracer.start_turn("x")
    tracer("gate", {"retrieve": False, "query": "", "reason": "x", "hits": 0,
                    "input_tokens": 50, "output_tokens": 10})
    totals = tracer.end_turn("ok")
    assert (totals["input_tokens"], totals["output_tokens"], totals["llm_calls"]) == (50, 10, 0)


def test_the_answer_comes_from_the_prompt_without_a_search_tool_call(tmp_path):
    """Step 5 needed search_notes calls in the loop. Now the note is already
    there on the first call, so one model call answers."""
    memory = _memory(tmp_path)
    session = _session(tmp_path, memory=memory, gate=_gate(True, "brother birthday"))
    client = ScriptedClient([reply("June 20.")])
    messages = session.build_messages("When is Swapnil's birthday?")
    answer = run_loop(client, "fake-model", messages, build_registry(memory))

    assert answer == "June 20."
    assert len(client.calls) == 1
    assert "June 20" in client.calls[0]["messages"][0]["content"]
