"""Tools: what the model can do besides talk.

A tool is three things: a schema the model reads, a name, and a Python
function that runs. Step 1 has one tool and keeps them in two plain objects;
step 2 replaces this with a registry.

YOUR CODE (step 1). See docs/steps/01-the-loop.md.
"""

from __future__ import annotations

# TODO: the OpenAI-shape function schema for get_time (one required string
# argument, "timezone", an IANA name like "Asia/Tokyo").
GET_TIME_SCHEMA: dict = {}


def get_time(timezone: str) -> str:
    """Return the current time in `timezone` as an ISO-8601 string with its
    UTC offset, for example 2026-10-11T09:00:00+09:00. Standard library only."""
    raise NotImplementedError("step 1: write get_time")


TOOL_FNS = {"get_time": get_time}
