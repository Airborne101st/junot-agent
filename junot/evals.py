"""Run the evals:  uv run python -m junot.evals

Every case in evals/cases.jsonl is a real question for the real Junot (your
model, your SOUL.md, your skills), answered in its own throwaway home folder,
so your notes in data/ are never read or changed. For each case:

  1. seed the case's notes, then send its turns through Junot.respond()
  2. check the tools: calls it expected, and calls it must not make
  3. ask the judge to score the final reply against the case's rubric

Then the release gate compares the run with evals/baseline.json and says
ship (exit 0) or block (exit 1), with its reasons.

    uv run python -m junot.evals                    # run all, compare, decide
    uv run python -m junot.evals --case trip-skill  # just one case
    uv run python -m junot.evals --save-baseline    # this run becomes the baseline

A run costs real tokens: about 10 cases x (gate + Junot + judge). The total is
printed at the end, like every receipt.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from junot.app import Junot
from junot.client import get_client
from junot.config import Settings, load_settings
from junot.judge import grade
from junot.release import decide

ROOT = Path(__file__).resolve().parent.parent / "evals"
CASES = ROOT / "cases.jsonl"
BASELINE = ROOT / "baseline.json"
RESULTS = ROOT / "results"


def load_cases(path: Path = CASES) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def check_tools(case: dict, names: list[str]) -> list[str]:
    """The deterministic half: tool calls that should, or must not, happen."""
    problems = [f"expected a {tool} call" for tool in case.get("expect_tools", []) if tool not in names]
    problems += [f"{tool} was called but shouldn't be" for tool in case.get("forbid_tools", []) if tool in names]
    return problems


def run_case(case: dict, settings: Settings, client, workdir: Path, judge_model: str,
             today: str) -> dict:
    """One case, in `workdir` as Junot's home: never in settings.home."""
    soul = settings.home / "SOUL.md"
    if soul.exists():
        shutil.copy(soul, workdir / "SOUL.md")   # the persona under test is yours
    # Consolidation would add a summarizer call per case and change nothing graded.
    junot = Junot(replace(settings, home=workdir, consolidate_every=10**6), client=client)
    for fact in case.get("setup", []):
        junot.memory.add(fact["subject"], fact["content"])

    calls: list[dict] = []

    def collect(kind: str, event: dict) -> None:
        if kind == "tool":
            calls.append({"name": event["name"], "arguments": event["arguments"], "output": event["output"]})

    tokens = [0, 0]
    reply, turn_error = "", ""
    for text in case["turns"]:
        turn = junot.respond(text, conversation="eval", observer=collect)
        reply, turn_error = turn.reply, turn.error or turn_error
        tokens[0] += turn.totals.get("input_tokens", 0)
        tokens[1] += turn.totals.get("output_tokens", 0)
    junot.memory.close()   # not close(): nothing to learn from an eval

    problems = check_tools(case, [call["name"] for call in calls])
    verdict = grade(client, judge_model, case["rubric"], case["turns"], reply, calls, today)
    return {
        "id": case["id"], "turns": case["turns"], "reply": reply, "tools": calls,
        "checks": problems, "checks_passed": not problems,
        "score": verdict.score, "passed": verdict.passed, "reason": verdict.reason,
        "error": verdict.error, "turn_error": turn_error,
        "input_tokens": tokens[0] + verdict.input_tokens,
        "output_tokens": tokens[1] + verdict.output_tokens,
    }


def run_all(cases: list[dict], settings: Settings, client, judge_model: str, show=print) -> list[dict]:
    today = datetime.now().astimezone().strftime("%A, %Y-%m-%d")
    results = []
    for case in cases:
        with tempfile.TemporaryDirectory(prefix=f"junot-eval-{case['id']}-") as workdir:
            result = run_case(case, settings, client, Path(workdir), judge_model, today)
        results.append(result)
        status = "ERROR" if result["error"] else ("pass" if result["passed"] and result["checks_passed"] else "FAIL")
        show(f"  {status:5}  {result['score']}/5  {case['id']:26} {result['reason'][:70]}")
        for problem in result["checks"]:
            show(f"         check: {problem}")
    return results


def load_baseline(path: Path = BASELINE) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def baseline_from(results: list[dict], model: str, judge_model: str) -> dict:
    return {"saved": datetime.now().astimezone().isoformat(timespec="seconds"),
            "model": model, "judge_model": judge_model,
            "cases": {r["id"]: {"score": r["score"], "passed": r["passed"],
                                "checks_passed": r["checks_passed"]} for r in results}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m junot.evals", description="Run Junot's evals and the release gate.")
    parser.add_argument("--case", action="append", help="run only this case id (repeatable)")
    parser.add_argument("--save-baseline", action="store_true", help="save this run as evals/baseline.json")
    args = parser.parse_args(argv)

    settings = load_settings()
    judge_model = os.getenv("JUNOT_JUDGE_MODEL", settings.model)
    cases = load_cases()
    if args.case:
        cases = [c for c in cases if c["id"] in args.case]
        if not cases:
            print(f"No case named {', '.join(args.case)}.")
            return 1

    print(f"Junot evals: {len(cases)} case(s), model {settings.model}, judge {judge_model}")
    results = run_all(cases, settings, get_client(settings), judge_model)

    graded = [r for r in results if not r["error"]]
    average = sum(r["score"] for r in graded) / len(graded) if graded else 0.0
    passed = sum(r["passed"] and r["checks_passed"] for r in results)
    tokens = (sum(r["input_tokens"] for r in results), sum(r["output_tokens"] for r in results))
    print(f"\n  {passed}/{len(results)} passed · average {average:.2f}/5 · {tokens[0]} in / {tokens[1]} out")

    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    (RESULTS / f"{stamp}.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  every reply and grade: evals/results/{stamp}.json")

    baseline = load_baseline()
    if args.case and baseline:
        # A partial run is compared only on its own cases.
        baseline = {**baseline, "cases": {k: v for k, v in baseline["cases"].items() if k in args.case}}
    decision = decide(results, baseline)
    print(f"\n  release gate: {'SHIP' if decision.ship else 'BLOCK'}")
    for reason in decision.reasons:
        print(f"    - {reason}")

    if args.save_baseline:
        if any(r["error"] for r in results):
            print("\n  Not saving a baseline: some cases couldn't be graded.")
            return 1
        BASELINE.write_text(json.dumps(baseline_from(results, settings.model, judge_model), indent=2) + "\n",
                            encoding="utf-8")
        print("\n  saved evals/baseline.json: commit it, so the next change is compared with this one")
    return 0 if decision.ship else 1


if __name__ == "__main__":
    sys.exit(main())
