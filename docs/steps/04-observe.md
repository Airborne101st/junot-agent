# Step 4: the observer and the trace

**Goal:** know exactly what every turn did and cost, without the loop knowing
who's watching.

In step 1 you added `print` lines inside `run_loop` to see the tool calls.
That worked, but it had three problems:

1. **It only goes to the terminal.** A Telegram gateway (step 9) has no
   terminal. A web dashboard needs the same events, drawn differently.
2. **It's gone when you close the window.** "Why did yesterday's answer say
   that?" has no answer.
3. **The loop owns the output.** Every new place that wants to see a turn
   would mean editing the loop.

The fix is the pattern you saw in Waku's `agent.py`: the loop calls one
function, `observer(kind, event)`, every time something happens, and never
asks who it is. The terminal, a trace file and a future dashboard are each
just an observer.

**You write:**

| File | What |
|---|---|
| `junot/loop.py` | an `observer=None` parameter, and the two events below |
| `junot/observe.py` | `compose()` and `Tracer` (stubs are there) |

Already done for you: `junot/__main__.py` (a `console` observer for tool
lines, the tracer, and a one-line receipt after every reply) and
`junot/show_trace.py` (reads today's trace back). `tests/fakes.py`'s `reply()`
now takes `tokens=(prompt, completion)`.

**Done when:**

```bash
uv run pytest -v
```

passes all 61 tests, and after a turn in the REPL,

```bash
uv run python -m junot.show_trace
```

prints that turn: each model call with its tokens, each tool call with its
result, and the totals.

## 1. The loop emits two kinds of event

**`"llm"`**, once per model call, **including the tools-off final call**:

```python
{"iteration": 1,          # 1, 2, 3, ... ; the final call is max_iterations + 1
 "input_tokens": 120,     # response.usage.prompt_tokens
 "output_tokens": 8,      # response.usage.completion_tokens
 "tool_calls": 0,         # how many the model asked for
 "final": False}          # True only for the tools-off call at the limit
```

Some OpenAI-compatible providers send no `usage` at all. Then count zero
tokens; don't crash. (`getattr(response, "usage", None)`)

**`"tool"`**, once per tool call, right after it runs:

```python
{"name": "get_time",
 "arguments": '{"timezone": "Asia/Tokyo"}',   # the model's raw JSON string
 "output": "2026-10-18T...",
 "ok": True,                                   # False when output starts with "Error"
 "duration_ms": 0}                             # an int
```

`time.perf_counter()` before and after `tools.execute(...)` gives the
duration in seconds; multiply by 1000 and use `int()`.

`observer` defaults to `None`. Turn it into a do-nothing function once at the
top (`notify = observer or (lambda kind, event: None)`), so the rest of the
loop never checks for `None`. Same trick as Waku.

## 2. `compose`: several observers as one

`run_loop` takes one observer. `compose(console, tracer)` returns one
function that calls each of them in order. Two rules:

- `None` entries are skipped, so a caller can write `compose(maybe_none, tracer)`.
- **An observer that raises must not stop the others, or the turn.** Watching
  a turn must never be able to break it. If the disk under the trace file is
  full, you still get your answer. Catch `Exception` around each call.

## 3. `Tracer`: every event, one JSON line

One file per day, `<folder>/<YYYY-MM-DD>.jsonl`, with the date taken from
`self.clock()`. Create the folder if it doesn't exist. Every line is one
`json.dumps({...})` followed by `"\n"`, opened in **append** mode (`"a"`),
and holds:

```python
{"ts": <clock().isoformat()>, "turn_id": <this turn's id>, "kind": <kind>, **event}
```

- `start_turn(user_message)`: a new `turn_id` (`uuid.uuid4().hex[:12]` is
  fine), reset the turn's counts to zero, write a `"turn_start"` line with
  `"user": user_message`, and return the id.
- `__call__(kind, event)`: this is what makes a `Tracer` an observer. Write
  the line, and add to the counts: each `"llm"` adds one call and its tokens,
  each `"tool"` adds one tool call.
- `end_turn(reply)`: write a `"turn_end"` line with the totals, and return
  them: `{"reply", "llm_calls", "tool_calls", "input_tokens", "output_tokens"}`.

The trace keeps tool outputs **whole**. History cuts them (step 3) because
the model re-reads history on every call. The trace is for you, and the
5,000th character is sometimes exactly what you need.

## Hints (only if stuck)

<details><summary>A class you can call like a function</summary>

Define `def __call__(self, kind, event):`. Then `tracer("llm", {...})` runs it,
and you can pass `tracer` anywhere an observer is expected.
</details>

<details><summary>Merging dicts</summary>

`{"ts": ..., "kind": kind, **event}` builds one dict holding both.
</details>

<details><summary>Appending a line to a file</summary>

```python
with open(path, "a", encoding="utf-8") as f:
    f.write(json.dumps(line) + "\n")
```
</details>

## After it passes, answer these

1. Ask Junot the time in Tokyo and Paris. In the trace, how much bigger is
   `input_tokens` on the second model call than the first? What's in the
   difference?
2. Have a five-turn conversation. Does each turn's first `input_tokens` grow?
   Connect that to step 3's question 3.
3. Why is the trace file JSONL (one JSON object per line) and not one big
   JSON array? Think about a turn that crashes halfway.
4. The trace keeps tool outputs and your messages whole, forever, in
   `~/.junot/traces`. What's the privacy cost of that, and what would you
   change before this ran on someone else's laptop? (Look at what Waku's
   `observability.py` does to `args` before writing them.)
