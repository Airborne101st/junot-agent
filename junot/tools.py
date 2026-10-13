"""Tools: what the model can do besides talk.

A tool is three things: a schema the model reads, a name, and a Python
function that runs. Step 1 has one tool and keeps them in two plain objects;
step 2 replaces this with a registry.

YOUR CODE (step 1). See docs/steps/01-the-loop.md.
"""

from __future__ import annotations
import datetime
from zoneinfo import ZoneInfo

# TODO: the OpenAI-shape function schema for get_time (one required string
# argument, "timezone", an IANA name like "Asia/Tokyo").


GET_TIME_SCHEMA: dict = {
"type": "function",
 "function":
     {
         "name": "get_time",
         "description": "Get the current time in a given timezone. Use whenever the user asks about the current date "
                        "or time anywhere in the world or needs today's date or current time to work something out",
         "parameters": {
         "type": "object",
         "properties": {
            "timezone": {
                "type": "string",
                "description": "An IANA timezone name, e.g. 'Asia/Tokyo'.",
            }
        },
        "required": ["timezone"]
         }
     }
}


def get_time(timezone: str) -> str:
    """Return the current time in `timezone` as an ISO-8601 string with its
    UTC offset, for example 2026-10-11T09:00:00+09:00. Standard library only."""
    try:
        tz = ZoneInfo(timezone)
    except Exception as e:
        raise ValueError(f"Invalid timezone: {timezone}") from e

    now = datetime.datetime.now(tz)
    return now.isoformat(timespec="seconds")



TOOL_FNS = {"get_time": get_time}
