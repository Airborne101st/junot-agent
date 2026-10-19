# Step 5: long-term memory

**Goal:** facts that survive a restart.

"Remember that my sister's birthday is 3 March." Quit. Start again. "When is
my sister's birthday?" Today Junot can't answer: history lives in the
`Session` object, and it's gone when the REPL closes.

This step adds the second kind of memory:

| | Working memory (step 3) | Long-term memory (this step) |
|---|---|---|
| lives in | the `Session` object | `data/state.db`, a SQLite file |
| holds | this conversation | short facts, one per row |
| survives a restart | no | yes |
| reaches the model | every turn, all of it | only when searched for |

**How the model reaches it, for now:** two tools. `save_note` when you tell
it something worth keeping, `search_notes` when a question needs something
you told it before. **The model decides when.** Step 6 adds the other way: a
gate that searches automatically before the model even starts.

**You write:**

| File | What |
|---|---|
| `junot/memory.py` | `fts_query` and `Memory` (stubs are there) |
| `junot/tools.py` | `save_note` and `search_notes`, and `build_registry(memory=None)` |

Already done for you: `junot/__main__.py` opens `Memory(settings.home /
"state.db")` and passes it to `build_registry`. **The REPL won't start until
`build_registry` accepts `memory`.**

**Done when:**

```bash
uv run pytest -v
```

passes all 84 tests, and in the REPL: "Remember that my sister's birthday is
3 March." → quit → start again → "When is my sister's birthday?" gets 3 March.
Then open the database and read the fact yourself:

```bash
sqlite3 data/state.db "SELECT rowid, subject, content, created FROM facts"
```

## 1. The table: one FTS5 virtual table

SQLite has a built-in full-text search engine, **FTS5**. A normal table finds
rows by exact values; an FTS5 table finds rows by the *words* in them, and
ranks the results (BM25, the classic search-engine ranking).

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS facts USING fts5(subject, content, created UNINDEXED)
```

- `subject` and `content` are searchable.
- `created` is stored but not searched (`UNINDEXED`); nobody looks a fact up
  by its timestamp text.
- Every FTS5 row has a hidden integer `rowid`. That's the fact's id.
- `IF NOT EXISTS` makes opening an existing database safe: on the second run
  the table is already there and nothing happens.

Why keyword search and not embeddings (vectors)? For one person's facts it's
fast, fully local, needs nothing installed, and you can read the whole index
with `sqlite3`. Waku makes the same choice (`waku/memory/semantic/store.py`).
The cost: "sibling" won't find "sister". You'll see that in review question 2.

## 2. Python's `sqlite3`, in five lines

```python
conn = sqlite3.connect(path)                     # opens, or creates, the file
conn.execute("CREATE ...")
cur = conn.execute("INSERT INTO facts (subject, content, created) VALUES (?, ?, ?)",
                   (subject, content, created))
conn.commit()                                    # without this, the write is lost on exit
cur.lastrowid                                    # the new row's id
```

**Every value goes in as a `?` parameter, never pasted into the SQL with an
f-string.** `f"... VALUES ('{content}')"` breaks on the first apostrophe
("sister's"), and with crafted text it runs whatever SQL the text contains.
That's SQL injection, and there's a test with `Robert'); DROP TABLE facts; --`.

Searching:

```python
conn.execute("SELECT rowid, subject, content, created FROM facts "
             "WHERE facts MATCH ? ORDER BY rank LIMIT ?", (query, limit))
```

`ORDER BY rank` gives the best match first. `.fetchall()` (or just looping
over the result) gives tuples; turn each into a dict with the four keys.

## 3. `fts_query`: user text is not a query

`MATCH` takes FTS5's own query language, not plain text. An apostrophe or a
quote is a syntax error, and `AND`, `OR`, `NOT` and `NEAR` are operators. So
`search()` never passes the user's text straight in. `fts_query` turns it
into a safe query:

```python
fts_query("what's up?")   ==  '"what" OR "s" OR "up"'
fts_query("??")           ==  ""
```

1. Pull out the words: `re.findall(r"\w+", text)`.
2. Put each in double quotes. Inside quotes, `NOT` is just the word "not".
3. Join with `" OR "`, so a fact matching *any* word is found, and BM25 puts
   facts matching *more* words first.

If `fts_query` returns `""`, `search` returns `[]` without asking SQLite.

## 4. The tools

`build_registry(memory=None)`: always register `get_time`. If `memory` is
given, also register `save_note` and then `search_notes`.

The tool functions need the `memory` object, but the model only supplies
`subject` and `content`. Define them **inside** `build_registry`, so they can
see `memory`. It's the closure from `compose` again:

```python
def build_registry(memory=None):
    ...
    if memory is not None:
        def save_note(subject: str, content: str) -> str:
            ...           # `memory` is visible here
        registry.register(Tool("save_note", ..., fn=save_note))
```

**`save_note(subject, content)`**
- If `content` is empty or only spaces, **raise** `ValueError`. Your registry
  turns that into `"Error running save_note: ..."` for the model.
- Otherwise store it and return `f"Saved note #{id} to {memory.path}."`.
  Say exactly where it went; no claims the tool can't back up.

**`search_notes(query)`**
- One line per hit, for example
  `#3 [sister] Her birthday is 3 March. (saved 2026-10-19)`.
- No hits: say so plainly (`"No notes match 'volcano'."`). That's an answer,
  not an error, so don't start it with "Error".

**The descriptions matter more than the code.** They're the only thing that
tells the model *when* to save and *when* to search. Write them for the model:
what counts as worth saving (people, plans, preferences, durable facts, not
chit-chat), and that it should search before answering anything about your
life. The tests only check that they're longer than 40 characters; review
will check what they say.

## After it passes, answer these

1. Ask "When is my sister's birthday?" and look at the trace. What `query`
   did the model send? Did it search at all? Try "what do you know about my
   family?". Does it search, and for what?
2. Save "My sister's birthday is 3 March", then search for "sibling". What
   comes back, and why? What would fix it, and what would that cost?
3. Save a few unrelated notes, then search "what is my favourite food". Why
   might notes about other things match? (Hint: which words did `fts_query`
   turn that question into?) Step 6's gate rewrites the query; this is why.
4. Ask Junot to remember something, then to forget it. What happens? What's
   missing from this design?
