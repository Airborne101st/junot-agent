# Step 2: the harness around the loop

**Goal:** a turn that can't crash because of a tool, and can't run forever.

Step 1's experiments showed both failures. `Mars/Olympus` raised inside the
tool and an unknown tool raised a `KeyError` in the loop. Either way the
program died and the model never learned what went wrong. And `while True`
had no limit: a model that keeps asking for tools keeps you paying.

**You write:**

| File | What |
|---|---|
| `junot/registry.py` | `Tool.to_api()` and `ToolRegistry` (stubs are there) |
| `junot/tools.py` | `GET_TIME` as a `Tool`, and `build_registry()` returning a registry holding it |
| `junot/loop.py` | the new `run_loop` signature, the cap, the final answer, `LIMIT_NOTE` and `LIMIT_REPLY` |

Already updated for you: `junot/__main__.py` and the step 1 tests now use the
registry. **Step 1's tests fail until you finish step 2.** That's expected,
because the signature changed under them.

**Done when:**

```bash
uv run pytest -v
```

passes all 26 tests, and in the REPL "What time is it in timezone
Mars/Olympus? Use the tool." gets a sensible answer instead of a traceback.

## 1. The registry: errors become text

```python
class ToolRegistry:
    def register(self, tool: Tool) -> None
    def get(self, name: str) -> Tool | None
    def schemas(self) -> list[dict]           # every tool's to_api(), in order
    def execute(self, name: str, arguments: str) -> str
```

`execute` takes the model's **raw JSON string**, so parsing is part of what
can fail safely. It must **never raise**. Each of these returns a string
starting with `"Error"` that names the tool:

1. a name that isn't registered
2. arguments that aren't valid JSON
3. arguments the function doesn't accept (`fn(**args)` raises `TypeError`)
4. any exception inside the function: **include its message**, because the
   model can only recover if it knows *why*

The idea to take away: **a tool error is an observation, not a crash.** The
model reads it like any other result and decides what to do next: retry with
different arguments, try something else, or tell the user.

## 2. The loop: a cap and a tools-off final answer

```python
LIMIT_NOTE: str    # to the MODEL: no more tools, answer from what you have
LIMIT_REPLY: str   # to the HUMAN: used only if even the final call fails

def run_loop(client, model, messages, tools: ToolRegistry, max_iterations: int = 10) -> str
```

- At most `max_iterations` normal calls.
- If the model is still asking for tools after the last one, make **one more
  call** with `tool_choice="none"`, and with `LIMIT_NOTE` added as a final
  `{"role": "user", ...}` message. **Send** the note, but **don't append it**
  to `messages`: it's an instruction for this one call, not something the
  user said. (Hint: `messages + [note]` builds a new list.)
- If that call answers, append the answer to `messages` and return it.
- If it raises, or answers with no text, return `LIMIT_REPLY`.
- Normal calls don't pass `tool_choice` at all (a test checks this).

Why not just return `LIMIT_REPLY` straight away at the limit? Because by then
the turn has gathered real results, and you've paid for them. Waku learned
this the expensive way: 255k tokens and $0.54 of research, thrown away for a
canned message. Read the docstring of
`evals/deterministic/test_loop_limit_final_answer.py` in waku-agent after you
finish.

Why keep sending `tools` on the final call instead of leaving them out? The
history already contains tool calls, and some providers refuse a request that
has tool calls in its history but no tool definitions. `tool_choice="none"`
is the reliable way to say "don't call one".

## Rules for this step

- Write `LIMIT_NOTE` and `LIMIT_REPLY` yourself. Each one has a different
  reader; word each one for its reader.
- Remove your `print` debug lines before you commit (step 4 replaces them).
- `try/except Exception` is right in `execute` and around the final call. It
  is **not** right around the normal model calls yet: we haven't decided
  what a failed API call should do. That's a later step.

## After it passes, answer these

1. Run `Mars/Olympus` in the REPL. What exactly did the model receive, and
   what did it do with it?
2. Set `max_iterations=1` and ask for the time in three cities "one call at
   a time". What did the final answer say? Is that better or worse than an
   error, and for whom?
3. `execute` catches every `Exception`. Name one failure it should *not*
   hide from the model, or one it can't catch at all. (Think: what if the
   tool hangs forever?)
4. Open `waku/tools/registry.py`. What does Waku's `execute` do that yours
   doesn't, or the other way round?
