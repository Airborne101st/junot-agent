"""Step 10: the eval runner and the cases file. No model, no network.

    uv run pytest tests/test_step10_runner.py -v
"""

from __future__ import annotations

import json

from junot.config import PROJECT_SKILLS, Settings
from junot.evals import CASES, check_tools, load_cases, run_case
from junot.memory import Memory
from junot.tools import build_registry
from tests.fakes import ScriptedClient, reply, tool_call

GATE_NO = reply('{"retrieve": false, "query": "", "reason": "x"}')
GATE_YES = reply('{"retrieve": true, "query": "brother birthday", "reason": "x"}')


# ---- the cases file ---------------------------------------------------------------

def test_every_case_is_well_formed(tmp_path):
    cases = load_cases(CASES)
    assert len(cases) >= 10
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids)), "ids are unique"
    known_tools = {s["function"]["name"] for s in build_registry(Memory(tmp_path / "x.db")).schemas()}
    for case in cases:
        assert case["turns"] and all(isinstance(t, str) and t for t in case["turns"]), case["id"]
        assert len(case["rubric"]) > 20, case["id"]
        for tool in case.get("expect_tools", []) + case.get("forbid_tools", []):
            assert tool in known_tools, f"{case['id']}: no tool named {tool}"
        for fact in case.get("setup", []):
            assert fact["subject"] and fact["content"], case["id"]


# ---- tool checks ------------------------------------------------------------------

def test_an_expected_tool_that_wasnt_called_is_a_problem():
    assert check_tools({"expect_tools": ["get_time"]}, []) == ["expected a get_time call"]


def test_a_forbidden_tool_that_was_called_is_a_problem():
    assert check_tools({"forbid_tools": ["search_notes"]}, ["search_notes"]) == \
        ["search_notes was called but shouldn't be"]


def test_no_expectations_no_problems():
    assert check_tools({}, ["get_time", "save_note"]) == []


# ---- run_case ---------------------------------------------------------------------

def _settings(home) -> Settings:
    return Settings(api_key="x", model="main", small_model="small", home=home, skills_dir=PROJECT_SKILLS)


def test_a_case_runs_in_its_own_folder_and_never_touches_your_data(tmp_path):
    real = tmp_path / "data"
    real.mkdir()
    (real / "SOUL.md").write_text("You are Junot, aide to the General.", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    client = ScriptedClient([GATE_YES, reply("June 20, General."),
                             reply('{"score": 5, "reason": "Correct."}', tokens=(400, 20))])
    case = {"id": "recall", "turns": ["When is my brother's birthday?"], "forbid_tools": ["search_notes"],
            "setup": [{"subject": "brother", "content": "The user's brother's birthday is June 20."}],
            "rubric": "Says June 20."}
    result = run_case(case, _settings(real), client, work, "judge", "Monday, 2026-10-26")

    assert sorted(p.name for p in real.iterdir()) == ["SOUL.md"], "no state.db, no traces in your data"
    assert (work / "SOUL.md").read_text(encoding="utf-8") == "You are Junot, aide to the General."
    assert "The user's brother's birthday is June 20." in client.calls[1]["messages"][0]["content"], \
        "the case's note was seeded and recalled"
    assert result["reply"] == "June 20, General."
    assert result["score"] == 5 and result["passed"] is True and result["checks_passed"] is True
    assert client.calls[2]["model"] == "judge"


def test_tool_calls_are_collected_checked_and_shown_to_the_judge(tmp_path):
    client = ScriptedClient([GATE_NO, reply(tool_calls=[tool_call("get_time", {"timezone": "Asia/Tokyo"})]),
                             reply("It is 9pm in Tokyo."), reply('{"score": 5, "reason": "ok"}')])
    case = {"id": "tokyo", "turns": ["Time in Tokyo?"], "expect_tools": ["get_time"],
            "forbid_tools": ["save_note"], "rubric": "Gives Tokyo's time."}
    result = run_case(case, _settings(tmp_path / "data"), client, tmp_path, "judge", "Monday, 2026-10-26")
    assert [call["name"] for call in result["tools"]] == ["get_time"]
    assert result["checks"] == []
    assert "Asia/Tokyo" in client.calls[-1]["messages"][-1]["content"]


def test_every_turn_of_a_multi_turn_case_is_sent_and_the_last_reply_judged(tmp_path):
    client = ScriptedClient([GATE_NO, reply("It is noon."), GATE_NO, reply("I used get_time."),
                             reply('{"score": 4, "reason": "ok"}')])
    case = {"id": "two", "turns": ["Time?", "How do you know?"], "rubric": "Names the tool it used."}
    result = run_case(case, _settings(tmp_path / "data"), client, tmp_path, "judge", "today")
    assert result["reply"] == "I used get_time."
    assert "Time?" in client.calls[-1]["messages"][-1]["content"]


def test_a_judge_failure_is_kept_as_an_error(tmp_path):
    client = ScriptedClient([GATE_NO, reply("Hi."), RuntimeError("judge down")])
    case = {"id": "x", "turns": ["hi"], "rubric": "Says hello politely."}
    result = run_case(case, _settings(tmp_path / "data"), client, tmp_path, "judge", "today")
    assert result["passed"] is False and "judge down" in result["error"]
    json.dumps(result)   # the result must be saveable as JSON
