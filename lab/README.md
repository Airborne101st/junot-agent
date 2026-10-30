# lab

Experiments in harness engineering, one folder per topic, after the 13-step
roadmap (tagged `v1.0`). The roadmap code in `junot/` stays as it is; the lab
is where things get tried, measured and sometimes thrown away.

## How a topic works

1. Copy `_template/` to a folder named for the question, for example
   `lab/history-window/` or `lab/embeddings-vs-fts5/`.
2. Fill in its README: the question, the setup, what you measured, what you
   learned.
3. Put the code beside it. It may import from `junot/`; nothing in `junot/`
   ever imports from `lab/`.
4. Keep the topic even when the answer is "no": a dead end you wrote down is
   a dead end you never walk again.

## Promoting an idea to the product

The deployable assistant lives in its own repo, `junot`. A lab result moves
there by being copied over with its tests, never by importing across repos.

## Topics

| Topic | Question | Result |
|---|---|---|
| | | |
