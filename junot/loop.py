"""THE LOOP: reason, act, observe, repeat.

YOUR CODE (step 1). See docs/steps/01-the-loop.md.
"""

from __future__ import annotations

from collections.abc import Callable


def run_loop(
    client,
    model: str,
    messages: list[dict],
    tool_schemas: list[dict],
    tool_fns: dict[str, Callable[..., str]],
) -> str:
    """Run one agent turn and return the reply text.

    `messages` starts as [system, ...history, user] and is mutated in place:
    afterwards it holds every assistant message and tool result of the turn.
    """
    raise NotImplementedError("step 1: write the loop")
