# Step 9: one Junot, three gateways

**Goal:** talk to the same Junot from the terminal, a web page and Telegram,
without changing the loop.

Until now `__main__.py` built everything itself: the client, memory, tools,
tracer, gate, session, skills, and the order of a turn. A second front end
would have to copy all of that, and the copies would drift: fix a bug in one,
forget the other. That's exactly what happened to Waku's dashboard, which
once had two chat implementations.

So this step moves the wiring into one place, `junot/app.py`, behind one
method:

```python
junot = Junot(settings)
turn = junot.respond("When is my brother's birthday?", conversation="telegram:1234")
turn.reply, turn.totals, turn.error
```

and every front end becomes a **gateway**: get text from somewhere, call
`respond()`, send `turn.reply` back.

```
 terminal (__main__.py) ──┐
 web page (web.py)      ──┼──▶ Junot.respond(text, conversation) ──▶ session · gate · skills · loop · memory · tracer
 Telegram (telegram.py) ──┘
```

A test enforces the boundary: **a gateway may import `junot.app` and
`junot.config`, nothing else.** If one ever imports the loop, the session or
memory, the wiring has leaked out of `app.py` again.

**You write:** `junot/app.py` (`Junot`, its `session`, `respond`, `close`).

Already done for you: all three gateways, rewritten on top of `Junot`, and
the tracer now records each turn's conversation. Plus one fix found live,
explained below: `Memory` opens its connection with `check_same_thread=False`.

**Done when:**

```bash
uv run pytest -v
```

passes all 183 tests, and the same question works in all three:

```bash
uv run python -m junot           # the terminal
uv run python -m junot.web       # then open http://127.0.0.1:8765
uv run python -m junot.telegram  # needs a bot token, see section 4
```

## 1. Conversations: many histories, one memory

One Junot serves many **conversations**, each a string: `"cli"`, `"web"`,
`"telegram:<chat id>"`. Each gets its own `Session`, so its own history: your
Telegram chat doesn't see what you typed in the browser. All of them share
**one** `Memory`, because they're all you. Tell it something on the web, and
the gate finds it when you ask on Telegram. A test checks exactly that.

`session(conversation)` keeps a dict of sessions and creates one on first use,
with the memory, the gate, the skills folder and the observer, the same
arguments `__main__.py` used to pass.

Live, through the web gateway: "When is my brother's birthday?" then "And
what's his name?". The gate searched `'name person he him male'` for the
second (it can't see the first turn), and Junot still answered "Swapnil",
**from the conversation's history**. That's why history is per conversation.

## 2. `respond(text, conversation="cli", observer=None) -> Turn`

The order of a turn, which used to live in `__main__.py`:

1. `tracer.start_turn(text, conversation=conversation)`
2. `session = self.session(conversation)`, then `session.build_messages(text)`
3. `run_loop(...)` with the main model and the tools
4. `session.record(...)`
5. `maybe_consolidate(...)` with `every=settings.consolidate_every`
6. `totals = tracer.end_turn(reply)`, then return `Turn(reply, totals)`

**Observers.** Every event must reach three listeners: the global observer
from `__init__` (the terminal's console printer), the tracer, and this turn's
own `observer` (the web page collects the gate and tool lines for one reply).
The Session is created once, but the per-turn observer changes every turn.
So give the Session one method of yours, say `self._notify`, that calls
`compose(self.observer, self.tracer, self._turn_observer)`, and set
`self._turn_observer` at the start of each turn.

**Never raise.** Steps 2–5 go inside `try/except Exception`. On a failure,
the reply becomes a sentence that says what went wrong (include the error),
`error` is set, nothing is recorded, and the turn is still ended in the
trace. A gateway that crashes on one bad turn drops every later message; one
that gets a Turn just sends it.

**One turn at a time.** Hold a `threading.Lock` for the whole turn
(`with self._lock:`). Two Telegram messages can arrive together, and every
turn shares one memory connection and one tracer. Without the lock their
trace lines would interleave, and worse, their database writes could too.

## 3. The bug found live: SQLite and threads

The first end-to-end web run failed every turn with:

```
ProgrammingError: SQLite objects created in a thread can only be used in that same thread.
```

`Junot` (and its `sqlite3` connection) was built on the main thread, and the
server answered on another. `python -m junot.web` happens to serve on the
main thread, so it would have worked there. The test that ran the server in a
background thread is what found it. Two things fixed it together:
`check_same_thread=False` lets the connection cross threads, and the lock
makes sure only one thread uses it at a time. Neither is safe without the
other.

Notice also what the failure looked like: a reply saying "Junot couldn't
answer this time: ProgrammingError: …", and the server stayed up. That's
`respond()`'s never-raise rule working on its first day.

## 4. The gateways, briefly

- **Terminal** (`__main__.py`): reads lines, prints the reply and the
  receipt, and calls `close()` on quit so waiting exchanges are learned.
- **Web** (`web.py`): Python's own `http.server`, one page and `POST /chat`.
  It listens on **127.0.0.1 only**: reachable from this laptop and nowhere
  else. There's no login, so that address *is* the security model; `0.0.0.0`
  would let anyone on your Wi-Fi read your notes.
- **Telegram** (`telegram.py`): long polling with `urllib`, no dependency.
  To set it up:
  1. In Telegram, message **@BotFather**, send `/newbot`, and copy the token.
  2. Put it in `.env` as `JUNOT_TELEGRAM_TOKEN=...`. Never commit it; `.env`
     is gitignored.
  3. Start `uv run python -m junot.telegram` and message your bot. With an
     empty allow list it refuses you **and tells you your id**.
  4. Put that id in `.env` as `JUNOT_TELEGRAM_ALLOWED=...` and restart.

  The allow list matters more than anything else here. A bot is public:
  anyone who finds its name can message it, and without the list Junot would
  answer them from your notes. Strangers' messages never reach the model, the
  trace or memory. Also know that Telegram messages pass through Telegram's
  servers, unlike the web gateway.

## After it passes, answer these

1. Tell Junot something on the web page, then ask about it in the terminal.
   Does it know? Now ask "what did I just say?" in the terminal. Why do the
   two answers differ?
2. The gateways can't import the loop. Name one thing that would go wrong
   over time if `telegram.py` built its own `Session` and called `run_loop`
   directly.
3. Your Telegram bot's token is in `.env`. What could someone do with it if
   it leaked, and what does `JUNOT_TELEGRAM_ALLOWED` protect against that the
   token doesn't?
4. `respond()` holds a lock for the whole turn, which can take ten seconds.
   What does a second Telegram user experience meanwhile? When would that
   stop being acceptable, and what would you change?
