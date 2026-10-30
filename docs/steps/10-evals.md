# Step 10: evals, a judge, and a release gate

**Goal:** know whether a change made Junot better or worse, before you keep it.

For nine steps you've changed prompts and descriptions (SOUL.md, the gate,
the summarizer, `save_note`, two skills) and checked the result by reading a
few replies. Your 189 tests can't help there: they run a scripted fake model,
so they check the *code*, never the *answers*.

This step adds the other half, the way Waku does it (`waku/ops/release_gate.py`):

```
evals/cases.jsonl ──▶ for each case, in a throwaway home folder:
                        seed notes ─▶ Junot.respond(turns) ─▶ tool checks (expected / forbidden)
                                                          └─▶ judge model scores the reply 1–5 against a rubric
                   ──▶ results  ──▶ release gate: compare with evals/baseline.json ──▶ SHIP (exit 0) or BLOCK (exit 1)
```

```bash
uv run python -m junot.evals                     # all cases, then the gate's decision
uv run python -m junot.evals --case trip-skill   # one case, while you work on it
uv run python -m junot.evals --save-baseline     # this run is the new "last good"
```

## What the first real run found

A reference solution, your real SOUL.md, Gemini as both Junot and judge,
10 cases, **about 20,600 tokens in total**:

| Case | Score | What it found |
|---|---|---|
| date-from-the-clock | **1/5** | Junot called `get_time` for *today's date*. Your `get_time` description says "use whenever the user asks about the current **date**… or **needs today's date**". The same conflict as step 6's `search_notes`: a tool description beats the prompt. **A real bug no test could find.** |
| trip-skill | **2/5**, then **5/5** | Junot said "the trip was on October 23, 2026, which has already passed" and asked about a new one, exactly the skill's edge case. **The case was wrong, not Junot**: its date had gone by. Moved a year ahead, it scores 5. |
| forget-honestly | **1/5** | "The brother's name is no longer referenced." Still the empty promise from step 5. Expected; step 13 fixes it. |
| the other seven | 4–5/5 | recall without searching, sibling → brother, honest "I don't know", the tool error explained, the `get_time` source named (no pocket chronometer). |

Two lessons that are the whole point of this step:
- **Evals find what tests can't**, because they run the real model with your
  real prompts. The `get_time` description bug had been there since step 1.
- **Evals rot.** A case with a fixed date quietly started testing something
  else. When a case fails, check the case before the agent.

## The three parts

| Part | File | Who |
|---|---|---|
| Cases | `evals/cases.jsonl`: one JSON object per line: `id`, `turns`, optional `setup` notes, `expect_tools`, `forbid_tools`, and a `rubric` | provided; add your own |
| Judge | `junot/judge.py`: `JUDGE_PROMPT` and `grade()` | **you** |
| Gate | `junot/release.py`: `decide()` | **you** |
| Runner | `junot/evals.py`: isolation, tool checks, results, baseline, CLI | provided |

Each case runs in a **temporary home folder**, with only your SOUL.md copied
in. Your `data/` is never written: no notes, no chat log, no traces. A test
checks that, and so did the live run.

**Done when:**

```bash
uv run pytest -v
```

passes all 217 tests, and then:

```bash
uv run python -m junot.evals --save-baseline
```

runs every case and saves `evals/baseline.json`. Commit it.

## 1. The judge: `grade(client, model, rubric, turns, reply, tool_calls, today) -> Grade`

**`JUDGE_PROMPT`** is the most important text here: it decides what "good"
means. It gets four placeholders:

- `{rubric}`: what a good answer does, from the case
- `{today}`: the date, so it can check "what's today's date?"
- `{conversation}`: the user's turns and Junot's final reply, labelled
- `{tools}`: each call as `name(arguments) -> output`, or a line saying no
  tool was called (a blank invites the judge to guess)

Say what each score means (5 = everything the rubric asks, 1 = wrong or
invented), tell it to judge **against the rubric and the facts given, not
its own idea of the user**, and to ignore the persona's style ("Sir", 1700s
English) and judge only what is said and done. Then ask for **only** JSON:
`{"score": <1-5>, "reason": "<one sentence>"}`. Double the JSON example's
braces for `.format()`, as in the gate and the summarizer.

**The call:** `temperature=0`, no tools. A judge should be as repeatable as
it can be: same answer, same score. (It still won't be perfectly
repeatable. That's why the gate has a tolerance.)

**Fail closed.** Read the JSON as in the gate. Then check the score really is
an integer from 1 to 5. A missing score, the word "excellent", a 6, or a
failed call all return `Grade(score=0, passed=False, reason="", error=...)`.

Compare the two gates you've built:

| | Retrieval gate (step 6) | Judge and release gate (step 10) |
|---|---|---|
| on failure | **fails open**: searches anyway | **fails closed**: counts as not passed |
| why | a note you didn't need costs a few tokens | a change you couldn't check might reach you broken |

The same instinct, "make failure safe", gives opposite answers, because the
cost of each mistake is different.

## 2. The release gate: `decide(results, baseline) -> Decision`

A score alone means little: is 3.8 good? The question is "worse than the last
version I trusted?". The baseline is that version, saved per case.

Block (ship = False), with a reason naming the case, when:
- the judge couldn't grade a case (its `error` is set). **Even with no
  baseline**: fail closed.
- a case **passed in the baseline and fails now**: a regression.
- a case's **tool checks passed in the baseline and fail now**.
- the **average score** over the cases in both runs fell by more than
  `MAX_AVERAGE_DROP` (0.5). Every case can still pass while all got a bit
  worse together; that's a regression too.

Don't block when:
- a case **already failed in the baseline** (`forget-honestly`). Blocking on
  it would block every change until step 13. The gate guards against going
  *backwards*, not against old problems.
- a case is **new** since the baseline.
- there's **no baseline**: ship, with a reason saying to save one.

## How to use it

1. Before a change: `uv run python -m junot.evals --save-baseline`, then commit.
2. Make the change (edit SOUL.md, a description, a skill, the model).
3. `uv run python -m junot.evals`. SHIP: keep it, save a new baseline and
   commit. BLOCK: read the reasons, and each reply in `evals/results/`.

Fix the `get_time` description now: say it's for timezones **other than**
the user's own, because their date and time are already in the prompt. Then
run `--case date-from-the-clock`. That's the loop this step is for.

## After it passes, answer these

1. Run the full suite twice without changing anything. Do the scores match?
   What does that tell you about `MAX_AVERAGE_DROP`, and about trusting one run?
2. Junot and the judge are the same model (`gemini-3.6-flash`). What could go
   wrong when a model grades itself? Try `JUNOT_JUDGE_MODEL=gemini-3.5-flash-lite`:
   do the scores change?
3. Write a case for something you care about: a `birthday-plan` request, or
   your persona's rules. What makes a rubric easy for a judge to apply, and
   what makes it vague?
4. The suite costs about 20,000 tokens. When is it worth running: every
   commit, every prompt change, before a model switch? What would you run in
   CI, and what only by hand?
