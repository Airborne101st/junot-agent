# Step 3: the session (working memory, rebuilt every turn)

**Goal:** control exactly what the model sees on each turn, and rebuild it
from scratch every time.

**The model remembers nothing between API calls.** Each call is a stranger
reading a transcript you hand it. So "what does the agent know right now?"
has one precise answer: whatever is in `messages` for this call. This step
puts one object in charge of that list.

Three problems with the REPL as it stands:

1. **The system prompt is fixed at startup.** Ask "what's today's date?" at
   23:59 and again at 00:01, and the model has no idea a day passed. Change
   the persona and you must edit Python and restart.
2. **Raw tool results pile up.** Every `tool` message from every turn stays
   in the list and is re-sent on every later call. A 5,000-character search
   result from turn 1 is paid for again on turns 2, 3, 4...
3. **But if you just throw tool activity away, the model forgets it acted.**
   Waku hit this live: the user asked to book a meeting, then said something
   else, and the model booked it *again* because nothing in its history said
   it already had. Three bookings. (See `add_exchange` in
   `waku/runtime/session.py`.)

The fix for 2 and 3 together: keep the **gist** of what the tools did, as one
short line in the assistant's history entry, and drop the raw messages.

**You write:** `junot/session.py`: `DEFAULT_SOUL`, `tool_note`, and `Session`.

Already updated for you: `junot/__main__.py` now uses `Session`, and
`junot/config.py` has `settings.home` (`~/.junot`, or `JUNOT_HOME`).

**Done when:**

```bash
uv run pytest -v
```

passes all 44 tests, and in the REPL:
- "What's the date today?" is answered **without** calling `get_time`, because
  the system prompt already says.
- Editing `~/.junot/SOUL.md` mid-conversation changes the very next reply.

## The pieces

```python
DEFAULT_SOUL: str
def tool_note(turn: list[dict]) -> str

class Session:
    def __init__(self, home: Path, model: str, clock=<now, with timezone>)
    def soul(self) -> str
    def build_system(self) -> str
    def build_messages(self, user_message: str) -> list[dict]
    def record(self, user_message: str, turn: list[dict], reply: str) -> None
```

**`soul()`** reads `home / "SOUL.md"`. If it doesn't exist, write
`DEFAULT_SOUL` to it first. Never overwrite an existing one: after the first
run, the file *is* the persona. Waku calls this procedural memory at its
simplest: change a file, change the agent.

**`build_system()`** joins three things: the soul, the current time from
`self.clock()` (the day name, plus `now.isoformat(timespec="minutes")`, which
includes the UTC offset), and the model name. Call `self.clock()` **every
time**. Reading it once in `__init__` is the bug a test checks for.

Why is the clock passed in instead of calling `datetime.now()` directly?
Because a test can't control "now". Passing it in lets a test fix it at
14:30 on a known Thursday. Same idea as passing in `client`: **anything the
outside world controls gets passed in**, so tests can supply their own.

**`build_messages()`** returns `[system] + history + [user]` as a **new**
list. `run_loop` mutates the list it's given (appending tool calls and
results), so if you hand it `self.history` itself, the raw tool messages leak
straight into history.

**`tool_note(turn)`** looks only at the messages after the **last** `user`
message (earlier ones belong to old turns). For each tool call in an
assistant message, find its `tool` result by `tool_call_id`, and produce:

```
[tools used: get_time({"timezone": "Asia/Tokyo"}) -> 2026-10-15T14:30:00+09:00]
```

Several calls are joined with `"; "`. Cut each output to 200 characters. If
no tool ran, return `""`.

**`record()`** appends two plain messages to history: the user's message,
and the reply with the note on a new line after it (only when there is a
note). The system message and the raw `tool` messages are never stored.

## Hints (only if stuck)

<details><summary>Finding the last user message</summary>

Loop over `enumerate(turn)` and remember the index each time `role ==
"user"`. Or go backwards with `range(len(turn) - 1, -1, -1)`.
</details>

<details><summary>Matching results to calls</summary>

Build a dict first: `{m["tool_call_id"]: m["content"] for m in ... if
m["role"] == "tool"}`. Then each call looks up its own output by `id`.
</details>

<details><summary>Reading a file that may not exist</summary>

`path.exists()`, `path.write_text(text, encoding="utf-8")`,
`path.read_text(encoding="utf-8")`.
</details>

## After it passes, answer these

1. Ask "what time is it?" twice, a minute apart. Does it still call
   `get_time`? Should it, now that the prompt has the time? (Hint: what
   timezone is your clock in, and what if the user asks about Tokyo?)
2. Ask something with a tool, then "what did you just do?". What did the
   model see that let it answer? Now imagine the tool note didn't exist.
3. Your history grows by two messages every turn, forever. At what point is
   that a problem, and what would you do about it? (Look at
   `self.session.history[-window:]` in waku's `waku/app.py`, and find where
   `window` comes from.)
4. Open `waku/runtime/session.py`'s `build_system`. List everything Waku puts
   in its system prompt that yours doesn't. Pick one you'd add, and say why.
