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
uv run python -m junot      # talk to it in the terminal
uv run python -m junot.web  # ...or at http://127.0.0.1:8765
uv run python -m junot.evals  # real questions, a judge, and the release gate
```

## Learning in the lab

The roadmap is finished and tagged `v1.0`. New experiments go in
[`lab/`](lab/README.md), one folder per topic. The deployable assistant lives
in its own repo, `junot`.

## How each step works

Each step has a guide in `docs/steps/` and a test file in `tests/` that is its
spec. Write the code until the tests pass, then answer the review questions at
the end of the guide.

## Roadmap

| # | Step | Pillar | Done when |
|---|---|---|---|
| 1 | [The bare loop](docs/steps/01-the-loop.md) | Loop | "Time in Tokyo?" is answered via the tool |
| 2 | [Tool registry, errors as text, iteration cap, tools-off final answer](docs/steps/02-the-harness.md) | Loop | A tool that raises doesn't crash the turn |
| 3 | [Session: system prompt rebuilt per turn from SOUL.md, clock, history](docs/steps/03-the-session.md) | Harness | Editing SOUL.md changes behaviour, no code change |
| 4 | [Observer and JSONL traces with token counts](docs/steps/04-observe.md) | Ops | Any turn can be rebuilt from its trace |
| 5 | [Memory: SQLite FTS5 facts and a `save_note` tool](docs/steps/05-memory.md) | Memory | "Remember X", restart, it recalls X |
| 6 | [Retrieval gate (small model, JSON decision, fails open)](docs/steps/06-gate.md) | Memory | "2+2" skips retrieval, and the trace shows it |
| 7 | [Consolidation every N exchanges into facts and episodes](docs/steps/07-consolidation.md) | Memory | Facts appear without calling `save_note` |
| 8 | [Skills: SKILL.md files matched into the prompt](docs/steps/08-skills.md) | Memory | A new workflow is a markdown file |
| 9 | [One `Junot.respond()`, three gateways: terminal, web, Telegram](docs/steps/09-gateways.md) | Harness | Two front ends, zero loop changes |
| 10 | [Evals: LLM-as-judge and a release gate](docs/steps/10-evals.md) | Ops | A prompt or model change that lowers the score is blocked |
| 11 | [Timeouts: tools and model calls that hang](docs/steps/11-timeouts.md) | Loop | A tool that sleeps forever returns an error in seconds |
| 12 | [Trace privacy: file mode, retention, redaction](docs/steps/12-trace-privacy.md) | Ops | Traces are owner-only, expire after 30 days, and mask the secrets they recognise |
| 13 | [Memory admin: forget and correct notes](docs/steps/13-forget-and-correct.md) | Memory | "Forget my brother's name" deletes the row, and says so |

Tests come with every step, so there's no separate "add evals" step: you
never change the harness without a test that pins what it should do.
