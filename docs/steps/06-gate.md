# Step 6: the retrieval gate

**Goal:** the right notes in the prompt before the main model starts, and
none when the message doesn't need them.

Step 5's review showed the cost of leaving retrieval to the main model:

| Question | Step 5 | What went wrong |
|---|---|---|
| "Do I have a sibling?" | 3 calls, 3,879 tokens | "sibling" is in no note; the model retried with "brother" |
| "What do you know about my family?" | 6 searches | no note says "family"; the model guessed relatives one by one |
| "What is my favourite food?" | `"what" OR "is" OR "my" ...` | raw words match unrelated notes |

A **retrieval gate** answers one narrow question with one cheap call, before
the main model runs: *does this message need the user's memory, and if so,
what should I search for?* It's the same idea as Waku's
`waku/memory/retrieval_gate.py`, which calls it "hero moment #1".

```
message ──▶ gate (small model) ──yes, "brother sister"──▶ memory.search ──▶ notes in system prompt ──▶ main model
                               └─no────────────────────────────────────────────────────────────────▶ main model
```

**Measured on your own notes**, with a reference solution and Gemini:

| Question | Step 5 | Step 6 |
|---|---|---|
| "Do I have a sibling?" | 3 calls, 3,879 tokens | **1 call, 742 tokens** |
| "What is 17 times 4?" | (no memory needed) | gate says skip; memory never touched |

**You write:**

| File | What |
|---|---|
| `junot/gate.py` | `GATE_PROMPT` and `should_retrieve` (the `Decision` dataclass is there) |
| `junot/session.py` | `Session` takes `memory`, `gate` and `observer`, and recalls notes into the system prompt |

Already done for you: `settings.small_model` (`gemini-3.5-flash-lite`, or
`JUNOT_SMALL_MODEL`), the REPL passes the gate to the Session and prints a
`[gate]` line, the tracer counts the gate's tokens in the turn's total, and
`show_trace` shows the decision. **The REPL won't start until `Session`
accepts the new arguments.**

**Done when:**

```bash
uv run pytest -v
```

passes all 108 tests, and in the REPL "Do I have a sibling?" shows a `[gate]
search ...` line, **no** `[tool] search_notes` line, and a receipt far below
step 5's 3,879 tokens. "What is 17 times 4?" shows `[gate] skip`.

## 1. `should_retrieve(client, model, message) -> Decision`

One `client.chat.completions.create(model=model, messages=[...])` call, with
**no `tools`**. The only message is a user message: `GATE_PROMPT` with the
user's message in place of `{message}` (`GATE_PROMPT.format(message=...)`).

**Writing `GATE_PROMPT` is the real work of this step.** It must:
- say what the decision is: does answering this need facts the user told the
  assistant before (people, dates, plans, preferences, past events)?
- give the easy cases both ways: general knowledge, arithmetic, small talk →
  no; anything about the user's own life → yes.
- ask for search **keywords the notes are likely to contain**, including
  related words. That's how "sibling" finds "brother".
- demand **only** this JSON: `{"retrieve": true/false, "query": "...", "reason": "..."}`.

A trap: `.format()` treats every `{` and `}` as a placeholder. The literal
braces of the JSON example must be doubled, `{{` and `}}`, or `.format` raises
`KeyError`.

**Reading the reply.** Small models wrap JSON in ```` ```json ```` fences or add a
sentence. Take the text from the first `{` to the last `}` and `json.loads`
that (`text.index("{")`, `text.rindex("}")`).

**Failing open.** Wrap the whole thing in `try/except Exception`. On *any*
failure (the call raises, no `{` in the reply, broken JSON, empty reply),
return `Decision(True, message, "gate failed open (...)")`: search with the
message itself. Why open, not closed? A note you didn't need costs a few
tokens. A note you needed and skipped costs a wrong answer, and the user
can't tell.

Two more details the tests check:
- A `retrieve: true` with an empty `query` searches the message.
- Keep the gate's own tokens (`response.usage`) in the `Decision`. It's a
  model call; it costs money, and the receipt should say so.

## 2. The Session uses the gate

```python
Session(home, model, clock=..., memory=None, gate=None, observer=None)
```

`build_messages(user_message)` now passes the message on to
`build_system(user_message)`. Keep `build_system()` working with no
argument (the step 3 tests call it that way): give the parameter a default
of `""`.

When there is memory and a message:

1. Ask the gate: `decision = self.gate(user_message)`. No gate? Behave like a
   gate that always says yes, with the message as the query (fail open again).
2. If `decision.retrieve`, `self.memory.search(decision.query, limit=5)`.
3. Report it: `observer("gate", {"retrieve", "query", "reason", "hits",
   "input_tokens", "output_tokens"})`, where `hits` is how many notes came back.
   Use the same "None becomes a do-nothing function" trick as the loop.
4. If there are notes, add a section to the system prompt with one line per
   note, and say **that the notes were already searched, for what query, and
   to call `search_notes` only if they don't answer.** No notes: add nothing,
   so the prompt is exactly what it was in step 3.

Point 4's last sentence isn't decoration. Without it, the reference solution
still called `search_notes` twice for notes already in the prompt, because
the `search_notes` description says to search "before answering any question
about the user". With it: one call, 742 tokens.

## After it passes, answer these

1. Ask "What do you know about my family?". In the reference run it made
   **eight** searches and used 9,177 tokens, more than step 5. Why does an
   open-ended question defeat the gate? What would you change: the gate
   prompt, the memory section, the `search_notes` description, or the limit
   of 5?
2. The gate sees only the newest message. Ask "When is my brother's birthday?",
   then "And what's his name?". What does the gate decide for the second one,
   and why? What would it need to see?
3. The gate costs one extra call on *every* message, even "hi". When is that
   worth it, and when isn't it? Look at the gate's tokens in `show_trace`
   next to the main call's.
4. Your `search_notes` description and the new memory section now give the
   model two different instructions. Which one should win, and where should
   that rule live?
