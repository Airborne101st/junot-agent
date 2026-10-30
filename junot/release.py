"""The release gate: should this change ship?

An eval run scores every case. On its own a score says little: is 3.9 good?
What matters is the comparison with the last version you trusted, the
baseline (evals/baseline.json). The gate compares the two and says ship or
block, with every reason.

A case that already failed in the baseline doesn't block: "forget-honestly"
fails today, and blocking on it would block every change until step 13. What
blocks is a regression: something that used to work and doesn't any more.

YOUR CODE (step 10). See docs/steps/10-evals.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# How far the average score may fall before the gate blocks. A judge model
# isn't perfectly repeatable; a drop smaller than this is noise.
MAX_AVERAGE_DROP = 0.5


@dataclass
class Decision:
    ship: bool
    reasons: list[str] = field(default_factory=list)   # why it blocks, or notes when it ships


def decide(results: list[dict], baseline: dict | None) -> Decision:
    """`results` is this run: one dict per case with "id", "score",
    "passed", "checks_passed" and "error". `baseline` is the trusted run as
    {"cases": {id: {"score", "passed", "checks_passed"}}}, or None.

    Block when, for any case: the judge couldn't grade it (error); it passed
    in the baseline and fails now; its tool checks passed in the baseline
    and fail now. Block when the average score over the cases in both runs
    fell by more than MAX_AVERAGE_DROP. Cases new since the baseline never
    block. No baseline: ship, with a reason saying to save one."""
    # Fail closed, first and always: a case nobody could grade blocks, with
    # or without a baseline. "I couldn't check" is not "it's fine".
    reasons = [f"{r['id']}: the judge couldn't grade it ({r['error']})" for r in results if r.get("error")]

    if baseline is None:
        if reasons:
            return Decision(False, reasons)
        return Decision(True, ["no baseline yet: run with --save-baseline to set one"])

    before = baseline["cases"]
    # Only cases in both runs are compared: a new case has nothing to regress
    # from, and a hard new case mustn't look like everything got worse.
    common = [r for r in results if r["id"] in before and not r.get("error")]

    for result in common:
        then = before[result["id"]]
        if then["passed"] and not result["passed"]:
            reasons.append(f"{result['id']}: passed before (score {then['score']}), "
                           f"fails now (score {result['score']})")
        if then["checks_passed"] and not result["checks_passed"]:
            reasons.append(f"{result['id']}: its tool checks passed before and fail now")

    if common:
        average_then = sum(before[r["id"]]["score"] for r in common) / len(common)
        average_now = sum(r["score"] for r in common) / len(common)
        # Every case can still pass while all of them got a bit worse together.
        if average_then - average_now > MAX_AVERAGE_DROP:
            reasons.append(f"the average score fell from {average_then:.2f} to {average_now:.2f}")

    return Decision(not reasons, reasons)
