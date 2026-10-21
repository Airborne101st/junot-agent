# Step 7: consolidation

**Goal:** Junot learns notes from the conversation by itself.

Until now a fact reaches memory only when the main model decides to call
`save_note`. That's unreliable both ways: sometimes it saves nothing ("I'm
flying to Pune on Friday" is said in passing), and when it does save, the
notes look like your step 5 rows: `June 20th`, `Swapnil`. Facts that don't
say whose birthday, or what Swapnil is.

**Consolidation** is the fix Waku uses (`waku/memory/consolidation.py`):

```
every exchange ──▶ chat_log (consolidated = 0)
                       │
        every N exchanges (default 6)
                       ▼
     small model reads the waiting exchanges + the facts already known
                       │
          ┌────────────┴─────────────┐
          ▼                          ▼
   new facts ──▶ facts table    one episode ──▶ episodes table
   (what the gate searches)     ("2026-10-21: planned the Pune trip")
                       │
              mark the exchanges consolidated = 1
```

Why every N, not every message? One call per message costs a summarizer
call each time, and most messages hold no fact at all. A batch is cheaper,
and gives the summarizer enough context to tell a fact from small talk.

**Measured with a reference solution** on a copy of your notes, three
exchanges, no `save_note` tool: **one call, 813 tokens**, and it stored

```
The user's cousin Meera is having a wedding in Pune on Friday, October 23, 2026.
The user is allergic to peanuts.
```

Compare those with `June 20th`. Every lesson from your real data is in the
summarizer's prompt: one sentence that names its subject, "the user" instead
of the persona's name for you, and full dates.

**You write:**

| File | What |
|---|---|
| `junot/memory.py` | two tables and five methods (stubs with the table definitions are there) |
| `junot/session.py` | one addition: `record` logs the exchange when there is memory |
| `junot/consolidate.py` | `SUMMARIZER_PROMPT` and `maybe_consolidate` |

Already done for you: `settings.consolidate_every` (6, or
`JUNOT_CONSOLIDATE_EVERY`), the REPL calls `maybe_consolidate` after every
turn and once more on quit, prints a `[learn]` line, the tracer counts the
summarizer's tokens, and `show_trace` lists what was learned.

**Done when:**

```bash
uv run pytest -v
```

passes all 132 tests, and in the REPL: set `JUNOT_CONSOLIDATE_EVERY=3` in
`.env`, have three ordinary exchanges with a fact in them (no "remember"),
see `[learn] 3 exchange(s) -> ...`, then read the notes:

```bash
sqlite3 data/state.db "SELECT content FROM facts; SELECT date, summary FROM episodes"
```

## 1. Memory: the chat log and episodes

In `__init__`, create both tables next to `facts`, with `CREATE TABLE IF NOT
EXISTS`. Your real `data/state.db` only has `facts`; `IF NOT EXISTS` means
opening it just adds the two new tables and touches nothing else. (That's a
database **migration**, the simplest kind. A test checks it.)

```sql
CREATE TABLE IF NOT EXISTS chat_log (id INTEGER PRIMARY KEY, created TEXT NOT NULL,
    user TEXT NOT NULL, assistant TEXT NOT NULL, consolidated INTEGER NOT NULL DEFAULT 0)
CREATE TABLE IF NOT EXISTS episodes (id INTEGER PRIMARY KEY, date TEXT NOT NULL,
    summary TEXT NOT NULL)
```

These are ordinary tables, not FTS5. Nobody searches them by words.

- `log_exchange(user, assistant)`: insert with `created` from `self.clock()`;
  `consolidated` takes its default, 0. Return `lastrowid`.
- `unconsolidated()`: `WHERE consolidated = 0 ORDER BY id`, as dicts.
- `mark_consolidated(ids)`: `UPDATE chat_log SET consolidated = 1 WHERE id = ?`
  for each id. `conn.executemany(sql, [(i,) for i in ids])` runs it once per
  id. Note the `(i,)`: each set of parameters is a tuple, even with one value.
- `add_episode(date, summary)` and `episodes()`: like `add` and `all`.

`commit()` after every write, as in step 5.

## 2. The Session logs every exchange

At the end of `record`: if `self.memory` is set, `self.memory.log_exchange(
user_message, content)`, where `content` is the reply **with** its tool
note, the same text history keeps.

## 3. `maybe_consolidate(client, model, memory, every=6, observer=None)`

1. `rows = memory.unconsolidated()`. Fewer than `every`? Return `None`
   straight away: no call, no event.
2. Build the prompt: `{known}` is every stored fact's content, one per line
   (or "(nothing yet)"), and `{exchanges}` is each row as `User: ...` and
   `Assistant: ...`.
3. One call to `model`, no tools. Read the JSON from the first `{` to the
   last `}`, as in the gate. Keep the tokens (`_tokens` from `loop.py`).
4. Keep a fact only if it's a dict with non-empty `content`, and its content
   isn't already stored or already kept in this batch. Compare ignoring case
   and extra spaces: `" ".join(text.split()).casefold()`.
5. **Only now, write:** add the kept facts, add the episode (if not empty)
   with today's date (`memory.clock().date().isoformat()`), and mark every
   row consolidated.
6. Report: `observer("consolidation", {"exchanges", "facts", "episode",
   "input_tokens", "output_tokens"})`, where `facts` is the list of kept
   contents. Return a `ConsolidationResult`.

**Failure keeps everything.** Steps 2–4 go inside `try/except Exception`. On
any failure, report the event with `"facts": []` and an `"error"` that says
what went wrong, write **nothing**, mark **nothing**, and return `None`. The
exchanges stay waiting, and the next batch tries again.

That's why step 5 comes after the `try`: if you added facts and *then* the
JSON failed halfway, the exchanges would stay waiting and the next batch
would store those facts a second time. **Decide everything first, then
write.**

And remember step 6's lesson: a fallback you can't see hides a broken part.
The `"error"` field is how you'd notice a summarizer that has never worked.

## 4. `SUMMARIZER_PROMPT`

This is the most important text in the step: it decides what Junot
remembers about you, forever. Put in what your real notes taught you:

- extract durable facts about the user, their people, plans, dates and
  preferences; skip small talk, one-off questions, and anything about the
  assistant or its tools.
- **only what the user said or confirmed**, never the assistant's own
  guesses (remember the pocket chronometer).
- each fact's content is **one sentence that names its subject and reads on
  its own**: "The user's brother Swapnil's birthday is June 20", not "June 20th".
- call the person **"the user"**, never the persona's name for them.
- **full dates**, never "tomorrow" or "next week".
- **don't repeat what's already known** (the `{known}` list).
- plus one sentence for the episode, and **only** the JSON, by name.

The same `.format()` trap as the gate: double the braces of the JSON example.

## After it passes, answer these

1. In the reference run *with* `save_note` available, the main model saved
   both facts itself, so consolidation found nothing new. Now there are two
   ways a fact gets in. Which should own memory: the model during the
   conversation, or consolidation after it? What happens to `save_note`'s
   description if consolidation owns it?
2. The main model saved the Pune trip as "Flying to Pune on October 23,
   2026…", and later "where am I going on Friday?" missed it: the word
   "Friday" was gone. Consolidation's version kept "Friday, October 23,
   2026". What does that tell you about how to write a fact for a
   *keyword* search?
3. Junot now stores an episode every batch, and nothing ever reads them.
   Where should they reach the model, and for which questions? ("What did we
   talk about last week?")
4. The summarizer gets a fact wrong ("The user is allergic to all nuts"
   when you said peanuts). How would you find out, and what could you do
   about it today? Which roadmap step is that?
