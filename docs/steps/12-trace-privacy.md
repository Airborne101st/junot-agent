# Step 12: trace privacy

**Goal:** traces stay useful for debugging, and stop being a liability.

Your answer in step 4: "it can be leaked". Before this step, every trace file
was:

- `-rw-r--r--`: readable by **every account on the Mac**
- kept **forever**
- a record of **everything**: every message you typed, every tool's input and output

## Owner-only files (`observe.py`, `memory.py`)

- `traces/` is created `0700` and each file `0600`, via `os.open(..., 0o600)`, so
  a file is private from its first byte rather than fixed later.
- Older files are corrected to `0600` when a `Tracer` starts.
- `state.db` (your notes and chat log) is set to `0600` when `Memory` opens it.

## Retention

A `Tracer` deletes trace files older than `keep_days` when it starts: 30 by
default, `JUNOT_TRACE_DAYS` to change, `0` to keep everything. Only files
named like `2026-10-30.jsonl` are touched; anything else in the folder is
left alone. **Note:** the first time Junot starts after this step, traces
older than 30 days are deleted.

## Redaction

`redact()` runs on every line before it's written:

| Masked | Example |
|---|---|
| values under secret-looking keys | `{"api_key": ...}`, `{"Authorization": ...}` |
| secret phrases, also inside JSON strings | `my password is hunter2`, `'{"password": "hunter2"}'` in tool arguments |
| credential shapes, anywhere | Gemini keys (`AIza…`), `sk-…` keys, Telegram bot tokens, `Bearer …` |

What's kept: tool names, arguments and outputs, token counts, replies, so
`show_trace` still rebuilds a turn. A test checks that `input_tokens` and
"Spin is fun" survive, so the masking doesn't eat ordinary words.

**What this doesn't cover**, honestly: the chat log in `state.db` still holds
what you typed (it has to, for consolidation), and redaction is pattern
matching, so a secret in an unusual shape gets through. Treat it as a seatbelt,
not a guarantee: don't type real passwords to an agent that keeps logs.

Tests: `tests/test_step12_privacy.py`.
