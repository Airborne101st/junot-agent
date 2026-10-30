"""Tools: what the model can do besides talk.

A tool is three things: a schema the model reads, a name, and a Python
function that runs.
"""

from __future__ import annotations
import datetime
from zoneinfo import ZoneInfo
from junot.registry import Tool, ToolRegistry
from junot.memory import Memory


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
    name="get_time",
    description="Get the current time in a given timezone other than the user’s own. Use whenever the user asks about the current date "
                "or time anywhere in the world except user's own location or needs today's date or current time to work something out",
    parameters={
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


def build_registry(memory: Memory | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(GET_TIME)
    if memory is not None:
        def save_note(subject: str, content: str) -> str:
            if not content.strip():
                raise ValueError("content is empty; nothing to save")
            note_id = memory.add(subject, content)
            return f"Saved note #{note_id} to {memory.path}."

        registry.register(Tool(
            name="save_note",
            description="Stores the information in database which the user asked it to remember "
                        "It should be used only when the user wants to store a factual information "
                        "come up with a subject and content for the information and then store it using tool. "
                        "Use only when user wants you to store/remember/save some information "
                        "Resolve relative dates (‘tomorrow’, ‘next week’) to full dates using the current date.",
            parameters={
                "type": "object",
                "properties": {
                    "subject": {
                        "type": "string",
                        "description": "A one word or a couple of words subject of the information. It should state what the information is. e.g. 'My Birthday'",
                    },
                    "content": {
                        "type": "string",
                        "description": "The actual content of the information which is to be stored. Can be one word, or a line long. e.g. 'January 10'",
                    }
                },
                "required": ["subject", "content"]
            },
            fn=save_note
        ))

        def search_notes(query: str) -> str:
            results = memory.search(query)
            if not results:
                return "No notes match for this information"
            return '\n'.join(
                [f"#{result['id']} [{result['subject']}] {result['content']} (saved {result['created'][:10]})" for
                 result in results])

        registry.register(Tool(
            name="search_notes",
            description="Search long-term memory for facts the user told you in earlier conversations. "
                        "Use this before answering any question about the user, their people, dates, plans or preferences, even if you think you don’t know. "
                        "Get the stored information from the memory database from a provided query "
                        "it searches the database for information (query) and returns a string",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A search term to find relevant information in the memory database, e.g. 'My Birthday'.",
                    }
                },
                "required": ["query"]
            },
            fn=search_notes
        ))

    return registry
