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

        # ---- step 13: forget and correct. Both name the note by its #id, which
        # recalled notes and search_notes results both show.

        def _note_id(note_id) -> int:
            # Models send 4, "4" or "#4"; all mean the same note.
            return int(str(note_id).strip().lstrip("#"))

        def forget_note(note_id) -> str:
            fact = memory.forget(_note_id(note_id))
            if fact is None:
                raise ValueError(f"there is no note #{note_id}; search_notes shows the ids")
            return (f"Forgot note #{fact['id']} ({fact['subject']}): {fact['content']!r}. "
                    f"It is deleted from {memory.path} and can't be recovered.")

        registry.register(Tool(
            name="forget_note",
            description="Permanently delete one note from long-term memory. Use ONLY when the user asks you "
                        "to forget, delete or remove something they told you. Use the note's #id from the "
                        "notes in your instructions or from search_notes; if more than one note could be "
                        "meant, ask which first. Never say something is forgotten without calling this: "
                        "nothing else removes it.",
            parameters={
                "type": "object",
                "properties": {"note_id": {"type": "integer", "description": "The note's id, e.g. 4 for #4."}},
                "required": ["note_id"],
            },
            fn=forget_note,
        ))

        def correct_note(note_id, content: str) -> str:
            if not content.strip():
                raise ValueError("the corrected content is empty; use forget_note to delete a note")
            before = memory.correct(_note_id(note_id), content.strip())
            if before is None:
                raise ValueError(f"there is no note #{note_id}; search_notes shows the ids")
            return f"Corrected note #{before['id']}: was {before['content']!r}, now {content.strip()!r}."

        registry.register(Tool(
            name="correct_note",
            description="Replace the content of one note that is wrong or out of date, when the user corrects "
                        "something they told you before. Use the note's #id from the notes in your "
                        "instructions or from search_notes. Write the new content as one sentence that names "
                        "its subject, with full dates.",
            parameters={
                "type": "object",
                "properties": {
                    "note_id": {"type": "integer", "description": "The note's id, e.g. 4 for #4."},
                    "content": {"type": "string", "description": "The corrected note, one full sentence."},
                },
                "required": ["note_id", "content"],
            },
            fn=correct_note,
        ))

    return registry
