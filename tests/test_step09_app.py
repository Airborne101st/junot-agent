"""Step 9: one Junot behind every gateway. These tests are the spec for app.py.

    uv run pytest tests/test_step09_app.py -v

Every respond() makes a gate call first (memory is always on), then the
loop's calls, then, when due, the summarizer's. The scripts below follow
that order.
"""

from __future__ import annotations

import json

from junot.app import Junot, Turn
from junot.config import Settings
from tests.fakes import ScriptedClient, reply, tool_call

SKIP = '{"retrieve": false, "query": "", "reason": "small talk"}'


def _gate(retrieve: bool = False, query: str = ""):
    return reply(json.dumps({"retrieve": retrieve, "query": query, "reason": "test"}), tokens=(50, 10))


def _settings(tmp_path, every: int = 6) -> Settings:
    skills = tmp_path / "skills"
    skills.mkdir(exist_ok=True)
    return Settings(api_key="x", model="main-model", small_model="small-model", home=tmp_path,
                    skills_dir=skills, consolidate_every=every)


def _junot(tmp_path, script, every: int = 6, observer=None) -> tuple[Junot, ScriptedClient]:
    client = ScriptedClient(script)
    return Junot(_settings(tmp_path, every), client=client, observer=observer), client


def _trace(tmp_path) -> list[dict]:
    [path] = (tmp_path / "traces").glob("*.jsonl")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ---- one turn --------------------------------------------------------------------

def test_respond_returns_the_reply_and_the_receipt(tmp_path):
    junot, _ = _junot(tmp_path, [_gate(), reply("Hello, General.", tokens=(300, 20))])
    turn = junot.respond("hi")
    assert isinstance(turn, Turn)
    assert turn.reply == "Hello, General."
    assert turn.error == ""
    assert turn.totals["llm_calls"] == 1
    assert turn.totals["input_tokens"] == 350, "the gate's 50 plus the main call's 300"


def test_the_gate_uses_the_small_model_and_the_loop_the_main_one(tmp_path):
    junot, client = _junot(tmp_path, [_gate(), reply("Hello.")])
    junot.respond("hi")
    assert [call["model"] for call in client.calls] == ["small-model", "main-model"]


def test_every_turn_is_traced_with_its_conversation(tmp_path):
    junot, _ = _junot(tmp_path, [_gate(), reply("Hello.")])
    junot.respond("hi", conversation="telegram:42")
    lines = _trace(tmp_path)
    assert lines[0]["kind"] == "turn_start"
    assert lines[0]["user"] == "hi" and lines[0]["conversation"] == "telegram:42"
    assert lines[-1]["kind"] == "turn_end" and lines[-1]["reply"] == "Hello."


def test_soul_md_is_created_in_the_home_folder(tmp_path):
    junot, _ = _junot(tmp_path, [_gate(), reply("Hello.")])
    junot.respond("hi")
    assert (tmp_path / "SOUL.md").exists()


# ---- conversations ----------------------------------------------------------------

def test_one_conversation_keeps_its_history(tmp_path):
    junot, client = _junot(tmp_path, [_gate(), reply("Noted, Pune."), _gate(), reply("Pune.")])
    junot.respond("I'm going to Pune.", conversation="web")
    junot.respond("Where am I going?", conversation="web")
    second_main_call = client.calls[3]["messages"]
    assert [m["role"] for m in second_main_call] == ["system", "user", "assistant", "user"]
    assert second_main_call[1]["content"] == "I'm going to Pune."


def test_two_conversations_have_separate_histories(tmp_path):
    junot, client = _junot(tmp_path, [_gate(), reply("Noted."), _gate(), reply("Hello.")])
    junot.respond("I'm going to Pune.", conversation="web")
    junot.respond("hi", conversation="telegram:42")
    telegram_call = client.calls[3]["messages"]
    assert [m["role"] for m in telegram_call] == ["system", "user"], "the web chat isn't in Telegram's history"


def test_the_same_conversation_gets_the_same_session(tmp_path):
    junot, _ = _junot(tmp_path, [])
    assert junot.session("web") is junot.session("web")
    assert junot.session("web") is not junot.session("cli")


def test_all_conversations_share_one_memory(tmp_path):
    """You told it on the web; you ask on Telegram. It's the same you."""
    junot, client = _junot(tmp_path, [
        _gate(),
        reply(tool_calls=[tool_call("save_note", {"subject": "brother",
                                                  "content": "The user's brother is Swapnil."})]),
        reply("Saved."),
        _gate(True, "brother"),
        reply("Your brother is Swapnil."),
    ])
    junot.respond("Remember my brother is Swapnil.", conversation="web")
    junot.respond("Who is my brother?", conversation="telegram:42")
    assert "The user's brother is Swapnil." in client.calls[4]["messages"][0]["content"]


# ---- observers ----------------------------------------------------------------------

def test_the_global_observer_sees_every_turn(tmp_path):
    seen = []
    junot, _ = _junot(tmp_path, [_gate(), reply("a"), _gate(), reply("b")],
                      observer=lambda kind, event: seen.append(kind))
    junot.respond("one")
    junot.respond("two", conversation="web")
    assert seen.count("gate") == 2 and seen.count("llm") == 2


def test_a_turns_own_observer_sees_only_that_turn(tmp_path):
    junot, _ = _junot(tmp_path, [_gate(), reply("a"), _gate(), reply("b")])
    first, second = [], []
    junot.respond("one", observer=lambda kind, event: first.append(kind))
    junot.respond("two", observer=lambda kind, event: second.append(kind))
    assert first == ["gate", "skills", "llm"] and second == ["gate", "skills", "llm"]


# ---- consolidation and closing -------------------------------------------------------

def test_consolidation_runs_when_due(tmp_path):
    summary = reply(json.dumps({"facts": [{"subject": "travel", "content": "The user is going to Pune."}],
                                "episode": "Talked about Pune."}))
    junot, client = _junot(tmp_path, [_gate(), reply("Nice."), _gate(), reply("Sure."), summary], every=2)
    junot.respond("I'm going to Pune.")
    junot.respond("Thanks.")
    assert client.calls[4]["model"] == "small-model"
    assert "Pune" in client.calls[4]["messages"][-1]["content"]


def test_close_learns_from_what_is_still_waiting(tmp_path):
    summary = reply(json.dumps({"facts": [{"subject": "travel", "content": "The user is going to Pune."}],
                                "episode": "Talked about Pune."}))
    junot, client = _junot(tmp_path, [_gate(), reply("Nice."), summary], every=6)
    junot.respond("I'm going to Pune.")
    junot.close()
    assert len(client.calls) == 3, "one exchange waiting, every=6: close() consolidates it anyway"


def test_close_with_nothing_waiting_makes_no_call(tmp_path):
    junot, client = _junot(tmp_path, [])
    junot.close()
    assert client.calls == []


# ---- a failure is an answer, not a crash ----------------------------------------------

def test_a_failed_model_call_becomes_a_reply_that_says_so(tmp_path):
    """A gateway that crashes on one bad turn drops every later message.
    respond() catches it, says so, and the next turn works."""
    junot, _ = _junot(tmp_path, [_gate(), RuntimeError("503 from the provider"), _gate(), reply("Back.")])
    turn = junot.respond("hi")
    assert "503 from the provider" in turn.error
    assert "503 from the provider" in turn.reply, "tell the person, don't go silent"
    assert junot.respond("still there?").reply == "Back."


def test_a_failed_turn_is_in_the_trace(tmp_path):
    junot, _ = _junot(tmp_path, [_gate(), RuntimeError("503 from the provider")])
    junot.respond("hi")
    end = _trace(tmp_path)[-1]
    assert end["kind"] == "turn_end"
    assert "503" in end["reply"]


# ---- threads: a gateway may answer on another thread ------------------------------

def test_respond_works_from_another_thread(tmp_path):
    """Found live: the web server answered on a background thread, and SQLite
    refused a connection made on the main one. Every turn failed."""
    import threading
    junot, _ = _junot(tmp_path, [_gate(), reply("From a thread.")])
    result = []
    worker = threading.Thread(target=lambda: result.append(junot.respond("hi", conversation="web")))
    worker.start()
    worker.join()
    assert result[0].error == "" and result[0].reply == "From a thread."


def test_two_turns_at_once_run_one_after_the_other(tmp_path):
    """Two messages arriving together must not interleave on one memory and
    one tracer: each turn's trace lines stay together."""
    import threading
    junot, _ = _junot(tmp_path, [_gate(), reply("a"), _gate(), reply("b")])
    threads = [threading.Thread(target=junot.respond, args=(text,), kwargs={"conversation": f"telegram:{i}"})
               for i, text in enumerate(["one", "two"])]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    kinds = [line["kind"] for line in _trace(tmp_path)]
    starts = [i for i, kind in enumerate(kinds) if kind == "turn_start"]
    ends = [i for i, kind in enumerate(kinds) if kind == "turn_end"]
    assert len(starts) == 2 and starts[1] > ends[0], "the second turn starts after the first one ends"
