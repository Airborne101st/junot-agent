# Step 1: the bare loop

**Goal:** the smallest thing that counts as an agent. A model that can ask for
a tool, a harness that runs it, and a loop that feeds the result back until
the model answers in plain text.

**You write:** `junot/tools.py` (the schema and `get_time`) and
`junot/loop.py` (`run_loop`). Everything else is plumbing that's already there.

**Done when:**

```bash
uv run pytest tests/test_step01_loop.py -v
```

passes, and `uv run python -m junot` answers "what time is it in Tokyo and
in Paris?" by calling `get_time` twice.

## The wire format (OpenAI Chat Completions, which Gemini speaks)

This is the one thing you can't derive from first principles, so here it is.

**Sending:**

```python
response = client.chat.completions.create(
    model=model,
    messages=messages,     # list of dicts
    tools=tool_schemas,    # list of {"type": "function", "function": {...}}
)
message = response.choices[0].message
```

**A tool schema:**

```python
{"type": "function",
 "function": {"name": "...", "description": "...",
              "parameters": {<a JSON Schema object>}}}
```

**What comes back:** `message.content` (str or None) and `message.tool_calls`
(None, or a list). Each tool call has `.id`, `.function.name` and
`.function.arguments`. **`arguments` is a JSON string, not a dict.**

**The four message roles your `messages` list will hold:**

```python
{"role": "system",    "content": "..."}
{"role": "user",      "content": "..."}
{"role": "assistant", "content": "..." or None,
 "tool_calls": [{"id": ..., "type": "function",
                 "function": {"name": ..., "arguments": "<json string>"}}]}
{"role": "tool",      "tool_call_id": ..., "content": "<result string>"}
```

The rule that trips everyone up: **every `tool` message must answer a
`tool_call_id` from the assistant message right before it.** So you have to
append the assistant's request to `messages` *before* the results, and
convert it to a plain dict yourself (the tests check this).

## Rules for this step

- Standard library only in `tools.py` (`zoneinfo` and `datetime` are enough).
- Loop until the model replies without tool calls. **Don't add an iteration
  cap or error handling yet.** Step 2 is about exactly those, and it's worth
  feeling their absence first.
- No reading Waku's `agent.py` while you write. Compare afterwards.

## Hints (only if stuck)

<details><summary>Hint 1: the shape</summary>

`while True:` call the model, append its message, if no tool calls return the
text, else run each and append each result.
</details>

<details><summary>Hint 2: calling the function</summary>

`json.loads(call.function.arguments)` gives a dict; `fn(**args)` calls it.
</details>

## After it passes, answer these (we'll discuss them in review)

1. What happens today if the model asks for a tool that isn't in `tool_fns`?
   What if `get_time` raises for `timezone="Mars/Olympus"`? Try it.
2. What stops your loop from running forever? Who decides when it ends?
3. Run the REPL and ask two questions in a row. The second call re-sends
   everything from the first. Where does that cost show up, and how would you
   measure it?
4. Now open `waku/loop/agent.py`. Name two things Waku does that you didn't,
   and why each one exists.
