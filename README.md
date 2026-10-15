# junot-agent

A personal agent harness, built one step at a time to learn harness
engineering. Modelled on the four pillars in
[waku-agent](https://github.com/ShenSeanChen/waku-agent): Loop, Harness,
Memory and Eval/Ops. Written from scratch, with no agent framework.

Model: Gemini, through its OpenAI-compatible endpoint, via the `openai` client.

## Setup

```bash
uv sync
cp .env.example .env        # paste GEMINI_API_KEY
uv run pytest               # offline; no key needed
uv run python -m junot      # talk to it
```

## How each step works

Each step has a guide in `docs/steps/` and a test file in `tests/` that is its
spec. Write the code until the tests pass, then answer the review questions at
the end of the guide.

## Roadmap

| # | Step | Pillar | Done when |
|---|---|---|---|
| 1 | [The bare loop](docs/steps/01-the-loop.md) | Loop | "Time in Tokyo?" is answered via the tool |
| 2 | [Tool registry, errors as text, iteration cap, tools-off final answer](docs/steps/02-the-harness.md) | Loop | A tool that raises doesn't crash the turn |
| 3 | Session: system prompt rebuilt per turn from SOUL.md, clock, history | Harness | Editing SOUL.md changes behaviour, no code change |
| 4 | Observer and JSONL traces with token counts | Ops | Any turn can be rebuilt from its trace |
| 5 | Memory: SQLite FTS5 facts and a `save_note` tool | Memory | "Remember X", restart, it recalls X |
| 6 | Retrieval gate (small model, JSON decision, fails open) | Memory | "2+2" skips retrieval, and the trace shows it |
| 7 | Consolidation every N exchanges into facts and episodes | Memory | Facts appear without calling `save_note` |
| 8 | Skills: SKILL.md files matched into the prompt | Memory | A new workflow is a markdown file |
| 9 | A second gateway (Telegram or web) on the same `respond()` | Harness | Two front ends, zero loop changes |
| 10 | LLM-as-judge eval and a release gate | Ops | A prompt or model change that lowers the score is blocked |

Tests come with every step, so there's no separate "add evals" step: you
never change the harness without a test that pins what it should do.
