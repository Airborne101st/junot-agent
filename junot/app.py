"""The app: one Junot, wired once, that any gateway can talk to.

Until step 8, __main__.py built everything itself: the client, memory, tools,
tracer, session, gate, skills, and the order of a turn. A second front end
would have to copy all of it, and the two copies would drift. So it moves
here, behind one method:

    junot = Junot(settings)
    turn = junot.respond("When is my brother's birthday?", conversation="telegram:1234")
    turn.reply, turn.totals

A gateway's whole job is then: get text from somewhere, call respond(), send
turn.reply back. The terminal, the web page and Telegram are three of those.

One Junot serves many conversations. Each conversation has its own Session
(its own history); all of them share one memory, because they're all you.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from junot.client import get_client
from junot.config import Settings
from junot.consolidate import maybe_consolidate
from junot.gate import should_retrieve
from junot.loop import run_loop
from junot.memory import Memory
from junot.observe import Tracer, compose
from junot.session import Session
from junot.tools import build_registry


@dataclass
class Turn:
    reply: str
    totals: dict = field(default_factory=dict)   # the receipt: Tracer.end_turn's totals
    error: str = ""                              # set when the turn failed; reply then says so


class Junot:
    def __init__(self, settings: Settings, client=None, observer=None) -> None:
        """Build everything once. `client` defaults to get_client(settings);
        tests pass a ScriptedClient. `observer` sees every event of every turn
        (the terminal's console printer, for example)."""
        self.settings = settings
        self.client = client or get_client(settings)
        self.observer = observer
        self.memory = Memory(settings.home / "state.db")
        self.tools = build_registry(self.memory)
        self.tracer = Tracer(settings.home / "traces", keep_days=settings.trace_keep_days)
        self.sessions: dict[str, Session] = {}
        # The current turn's own observer. Sessions are built once and hold
        # self._notify, which reads this on every event, so a per-turn
        # observer reaches them without rebuilding anything.
        self._turn_observer = None
        # One turn at a time: every turn shares one memory and one tracer.
        self._lock = threading.Lock()

    def _notify(self, kind: str, event: dict) -> None:
        """Every event goes to three listeners: the global observer, the
        tracer, and this turn's own observer. compose() skips the ones that
        are None, and never lets a broken one stop the others."""
        compose(self.observer, self.tracer, self._turn_observer)(kind, event)

    def _gate(self, message: str):
        return should_retrieve(self.client, self.settings.small_model, message)

    def session(self, conversation: str) -> Session:
        """The Session for this conversation, created on first use."""
        if conversation not in self.sessions:
            self.sessions[conversation] = Session(
                self.settings.home, self.settings.model,
                memory=self.memory, gate=self._gate, observer=self._notify,
                skills_dir=self.settings.skills_dir)
        return self.sessions[conversation]

    def respond(self, text: str, conversation: str = "cli", observer=None) -> Turn:
        """One whole turn: trace it, build the messages, run the loop, record
        it, consolidate if due. `observer` sees this turn's events only, on
        top of the global one. Never raises: a failure becomes a Turn whose
        reply says what went wrong and whose `error` is set.

        One turn at a time: a gateway may call this from several threads (two
        Telegram messages at once), and every turn shares one memory and one
        tracer. Hold a threading.Lock for the whole turn."""
        with self._lock:
            self._turn_observer = observer
            self.tracer.start_turn(text, conversation=conversation)
            error = ""
            try:
                session = self.session(conversation)
                messages = session.build_messages(text)
                reply = run_loop(self.client, self.settings.model, messages, self.tools,
                                 observer=self._notify)
                session.record(text, messages, reply)
                # Inside the turn, so the summarizer's tokens land on this receipt.
                maybe_consolidate(self.client, self.settings.small_model, self.memory,
                                  every=self.settings.consolidate_every, observer=self._notify)
            except Exception as exc:
                # A gateway that crashes on one bad turn drops every later
                # message. Say what went wrong, record nothing, carry on.
                error = f"{type(exc).__name__}: {exc}"
                reply = f"(Junot couldn't answer this time: {error})"
            totals = self.tracer.end_turn(reply)
            self._turn_observer = None
            return Turn(reply, totals, error)

    def close(self) -> None:
        """Learn from any exchanges still waiting (however few), then close
        the memory. Gateways call this when they stop."""
        with self._lock:
            if self.memory.unconsolidated():
                self.tracer.start_turn("(closing)")
                maybe_consolidate(self.client, self.settings.small_model, self.memory,
                                  every=1, observer=self._notify)
                self.tracer.end_turn("")
            self.memory.close()
