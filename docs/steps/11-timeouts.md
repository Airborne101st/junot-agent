# Step 11: timeouts

**Goal:** nothing can hang Junot. A tool that never returns, or a model call
that never answers, becomes an error the model reads, in seconds.

Step 2's review: you put `time.sleep(500)` in `get_time`, and the turn
waited 500 seconds. `try/except` catches what a tool *raises*; a hang raises
nothing. And since step 9, a hung turn holds the lock, so every gateway waits.

## Tools: a worker thread and a deadline (`registry.py`)

`ToolRegistry.execute` runs the tool on a worker thread and waits at most
`tool.timeout` seconds (10 by default; `Tool(..., timeout=30)` for a slow
one). If the thread is still running, the model gets:

```
Error: slow timed out after 10s and was abandoned (it may still finish in the background).
```

**Python can't kill a thread.** A timed-out tool is *abandoned*, not stopped,
and the message says so instead of claiming otherwise. For a tool that must
really be stopped (a shell command, a download), run it as a subprocess,
which can be killed. The worker is a daemon thread, so it never keeps Junot
from quitting.

## Model calls: a deadline instead of 10 minutes (`client.py`)

The OpenAI SDK waits up to **600 seconds** per call and retries twice, so one
stuck call could hold a turn for half an hour. `get_client` now sets
`timeout=settings.model_timeout` (60 s, or `JUNOT_MODEL_TIMEOUT`) and one
retry. A timeout raises inside `respond()`, which turns it into a reply that
says so (step 9's never-raise rule).

Tests: `tests/test_step11_timeouts.py`. A tool that would wait 30 seconds
returns "timed out" in under one.
