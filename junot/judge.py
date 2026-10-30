"""The judge: a model grading Junot's answer against a rubric.

Your 189 tests check code with a scripted fake model. They can't tell you
whether Junot's *answers* got better or worse when you change SOUL.md, the
gate prompt, a skill, or the model. That takes a real model answering real
questions, and something reading the answers. Reading them yourself after
every change doesn't scale; a judge model does.

Each eval case has a rubric: what a good answer does. The judge reads the
question, Junot's reply, the tools it called and the rubric, and scores it
1 to 5. Score 4 or more passes.

The judge fails CLOSED. The retrieval gate fails open, because a note you
didn't need costs little. A judge that can't grade must never look like a
pass: "I couldn't check" is not "it's fine".

YOUR CODE (step 10). See docs/steps/10-evals.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from junot.loop import _tokens

PASS_SCORE = 4

# Placeholders: {rubric}, {today}, {conversation} (the user's turns and
# Junot's final reply), {tools} (the tool calls Junot made, with results).
JUDGE_PROMPT = """
**Your job is to judge an answer from a personal assistant against a rubric.**
Here are the materials you will use:
Rubric: {rubric}
Today: {today}
Conversation:
{conversation}
Tools the assistant called:
{tools}

The rating scale: 5 - does everything the rubric asks, 4 - slight slip, 3 - partly correct,
2 - mostly wrong, 1 - either completely wrong or invents something.
Important rule: judge only against the rubric and the facts given, and ignore the persona's style.
The output:
Reply with ONLY this JSON: {{"score": <1-5>, "reason": "<one sentence>"}}
"""


@dataclass
class Grade:
    score: int              # 1-5, or 0 when the judge itself failed
    passed: bool            # score >= PASS_SCORE
    reason: str
    error: str = ""         # set when the judge couldn't grade
    input_tokens: int = 0
    output_tokens: int = 0


def grade(client, model: str, rubric: str, turns: list[str], reply: str,
          tool_calls: list[dict], today: str) -> Grade:
    """One call to `model`, temperature 0, no tools. `tool_calls` are dicts
    with "name", "arguments" and "output". Never raises: if the call fails
    or the reply has no usable score, return score 0, passed False, and the
    error. Scores outside 1-5 are an error too."""
    input_tokens = output_tokens = 0
    try:
        conversation = "\n".join(f"User: {t}" for t in turns) + f"\nAssistant (final reply): {reply}"
        tools = "\n".join(f"- {c['name']}({c['arguments']}) -> {c['output']}" for c in tool_calls)
        tools = tools or "(none: no tool was called)"

        response = client.chat.completions.create(
            model=model,
            temperature=0,   # as repeatable as a model can be: same answer, same score
            messages=[{"role": "user", "content": JUDGE_PROMPT.format(
                rubric=rubric, today=today, conversation=conversation, tools=tools)}],
        )
        input_tokens, output_tokens = _tokens(response)
        text = response.choices[0].message.content or ""
        data = json.loads(text[text.index("{"): text.rindex("}") + 1])

        # Trust nothing: a missing score raises KeyError here, and anything
        # that isn't a whole number from 1 to 5 is refused. bool is checked
        # because True is an int in Python, and {"score": true} isn't a grade.
        score = data["score"]
        if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
            raise ValueError(f"score {score!r} is not a whole number from 1 to 5")
        return Grade(score, score >= PASS_SCORE, str(data.get("reason", "")), "",
                     input_tokens, output_tokens)
    except Exception as exc:
        # Fail CLOSED: the retrieval gate's except says "search anyway"; this
        # one says "not passed". A judge that couldn't check must never look
        # like a judge that approved.
        return Grade(0, False, "", f"{type(exc).__name__}: {exc}", input_tokens, output_tokens)
