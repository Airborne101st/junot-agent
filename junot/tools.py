"""Tools: what the model can do besides talk.

A tool is three things: a schema the model reads, a name, and a Python
function that runs.
"""

from __future__ import annotations
import datetime
from zoneinfo import ZoneInfo
from junot.registry import Tool, ToolRegistry


def get_time(timezone: str) -> str:
    """Return the current time in `timezone` as an ISO-8601 string with its
    UTC offset, for example 2026-10-11T09:00:00+09:00. Standard library only."""
    try:
        tz = ZoneInfo(timezone)
    except Exception as e:
        raise ValueError(f"Invalid timezone: {timezone}") from e

    now = datetime.datetime.now(tz)
    return now.isoformat(timespec="seconds")

GET_TIME = Tool(
    name = "get_time",
    description= "Get the current time in a given timezone. Use whenever the user asks about the current date "
                  "or time anywhere in the world or needs today's date or current time to work something out",
    parameters= {
         "type": "object",
         "properties": {
            "timezone": {
                "type": "string",
                "description": "An IANA timezone name, e.g. 'Asia/Tokyo'.",
            }
        },
        "required": ["timezone"]
         },
    fn=get_time
)

def build_registry() -> ToolRegistry:
    tool_registry = ToolRegistry()
    tool_registry.register(GET_TIME)
    return tool_registry


