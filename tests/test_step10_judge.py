"""Step 10: the judge and the release gate. These tests are the spec.

    uv run pytest tests/test_step10_judge.py -v
"""

from __future__ import annotations

import json

from junot.judge import JUDGE_PROMPT, PASS_SCORE, Grade, grade
from junot.release import MAX_AVERAGE_DROP, decide
from tests.fakes import ScriptedClient, reply

RUBRIC = "Says the brother's birthday is June 20."
TOOLS = [{"name": "get_time", "arguments": '{"timezone": "Asia/Tokyo"}', "output": "2026-10-26T21:00:00+09:00"}]


def _grade(judge_reply, **kwargs) -> tuple[Grade, ScriptedClient]:
    client = ScriptedClient([judge_reply])
    args = {"rubric": RUBRIC, "turns": ["When is my brother's birthday?"], "reply": "June 20, General.",
            "tool_calls": TOOLS, "today": "Monday, 2026-10-26"} | kwargs
    return grade(client, "judge-model", **args), client


# ---- the judge ---------------------------------------------------------------------

def test_the_prompt_has_every_placeholder_and_asks_for_json():
    assert "JSON" in JUDGE_PROMPT
    for name in ("{rubric}", "{today}", "{conversation}", "{tools}"):
        assert name in JUDGE_PROMPT, name


def test_a_good_answer_passes():
    verdict, _ = _grade(reply('{"score": 5, "reason": "Gives June 20."}', tokens=(600, 30)))
    assert verdict == Grade(score=5, passed=True, reason="Gives June 20.", error="",
                            input_tokens=600, output_tokens=30)


def test_the_pass_mark_is_four():
    assert PASS_SCORE == 4
    assert _grade(reply('{"score": 4, "reason": "ok"}'))[0].passed is True
    assert _grade(reply('{"score": 3, "reason": "meh"}'))[0].passed is False


def test_the_judge_sees_the_rubric_the_conversation_the_tools_and_today():
    _, client = _grade(reply('{"score": 5, "reason": "ok"}'))
    sent = client.calls[0]["messages"][-1]["content"]
    for expected in (RUBRIC, "When is my brother's birthday?", "June 20, General.",
                     "get_time", "Asia/Tokyo", "2026-10-26T21:00:00+09:00", "Monday, 2026-10-26"):
        assert expected in sent, expected


def test_no_tools_is_said_plainly():
    _, client = _grade(reply('{"score": 5, "reason": "ok"}'), tool_calls=[])
    sent = client.calls[0]["messages"][-1]["content"]
    assert "get_time" not in sent
    assert "none" in sent.lower(), "tell the judge no tool was called, rather than leave a blank"


def test_one_call_to_the_judge_model_at_temperature_zero_with_no_tools():
    """A judge should be as repeatable as it can be: same answer, same score."""
    _, client = _grade(reply('{"score": 5, "reason": "ok"}'))
    [call] = client.calls
    assert call["model"] == "judge-model"
    assert call["temperature"] == 0
    assert "tools" not in call


def test_json_in_a_fence_is_read():
    verdict, _ = _grade(reply('Verdict:\n```json\n{"score": 2, "reason": "Wrong date."}\n```'))
    assert (verdict.score, verdict.passed, verdict.reason) == (2, False, "Wrong date.")


# ---- the judge fails closed -----------------------------------------------------------

def test_a_failed_call_is_a_failure_not_a_pass():
    verdict, _ = _grade(RuntimeError("503 from the provider"))
    assert verdict.score == 0 and verdict.passed is False
    assert "503 from the provider" in verdict.error


def test_a_reply_without_a_score_is_an_error():
    for bad in ("Looks good to me!", '{"reason": "no score"}', '{"score": "excellent", "reason": "x"}'):
        verdict, _ = _grade(reply(bad))
        assert verdict.passed is False and verdict.score == 0 and verdict.error, bad


def test_a_score_outside_one_to_five_is_an_error():
    for bad in (0, 6, 10, -1):
        verdict, _ = _grade(reply(json.dumps({"score": bad, "reason": "x"})))
        assert verdict.passed is False and verdict.error, bad


# ---- the release gate ---------------------------------------------------------------------

def _result(case_id: str, score: int, checks_passed: bool = True, error: str = "") -> dict:
    return {"id": case_id, "score": score, "passed": score >= PASS_SCORE and not error,
            "checks_passed": checks_passed, "error": error}


def _baseline(*results: dict) -> dict:
    return {"cases": {r["id"]: {"score": r["score"], "passed": r["passed"],
                                "checks_passed": r["checks_passed"]} for r in results}}


def test_without_a_baseline_it_ships_and_says_to_save_one():
    decision = decide([_result("a", 5)], None)
    assert decision.ship is True
    assert any("baseline" in reason for reason in decision.reasons)


def test_the_same_scores_ship():
    run = [_result("a", 5), _result("b", 4)]
    assert decide(run, _baseline(*run)).ship is True


def test_a_case_that_passed_and_now_fails_blocks():
    decision = decide([_result("a", 2), _result("b", 5)], _baseline(_result("a", 5), _result("b", 5)))
    assert decision.ship is False
    assert any("a" in reason for reason in decision.reasons), "name the case that regressed"


def test_a_case_that_already_failed_doesnt_block():
    """forget-honestly fails today. Blocking on it would block everything until step 13."""
    run = [_result("forget", 1), _result("b", 5)]
    assert decide(run, _baseline(_result("forget", 1), _result("b", 5))).ship is True


def test_a_case_that_now_passes_ships():
    assert decide([_result("a", 5)], _baseline(_result("a", 2))).ship is True


def test_failed_tool_checks_block_when_they_passed_before():
    decision = decide([_result("a", 5, checks_passed=False)], _baseline(_result("a", 5)))
    assert decision.ship is False


def test_a_case_the_judge_couldnt_grade_blocks():
    """Fail closed: "couldn't check" is not "fine"."""
    decision = decide([_result("a", 0, error="503")], _baseline(_result("a", 5)))
    assert decision.ship is False
    decision = decide([_result("a", 0, error="503")], None)
    assert decision.ship is False, "even without a baseline"


def test_an_average_drop_beyond_the_limit_blocks_even_with_no_single_regression():
    """Every case still passes (4 or 5) but all got worse together."""
    before = [_result(c, 5) for c in "abcd"]
    after = [_result(c, 4) for c in "abcd"]
    assert 5 - 4 > MAX_AVERAGE_DROP
    decision = decide(after, _baseline(*before))
    assert decision.ship is False
    assert any("average" in reason for reason in decision.reasons)


def test_a_small_average_drop_is_noise_and_ships():
    before = [_result(c, 5) for c in "abcd"]
    after = [_result("a", 4)] + [_result(c, 5) for c in "bcd"]
    assert decide(after, _baseline(*before)).ship is True


def test_a_new_case_never_blocks():
    decision = decide([_result("a", 5), _result("brand-new", 1, checks_passed=False)], _baseline(_result("a", 5)))
    assert decision.ship is True
