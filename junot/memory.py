"""Long-term memory: facts that survive a restart, in one SQLite file.

Working memory (session.py) is gone when the REPL closes. This is the other
kind: a table of short facts in <home>/state.db, searched by keyword with
SQLite's built-in full-text index, FTS5. No embeddings, no server, nothing to
install. Open the file with `sqlite3 data/state.db` and read every fact.

YOUR CODE (step 5). See docs/steps/05-memory.md.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

# The four columns every read returns, in the order the dicts are built from.
COLUMNS = "rowid, subject, content, created"


def fts_query(text: str) -> str:
    """Turn any user text into a safe FTS5 query: every word, double-quoted,
    joined by " OR ". "what's up?" -> '"what" OR "s" OR "up"'. "" if no words."""
    # Quoted, NOT and NEAR are plain words; unquoted, FTS5 reads them as
    # operators. OR between them finds a fact with any word, and FTS5's
    # ranking puts the facts with the most words first.
    return " OR ".join(f'"{word}"' for word in re.findall(r"\w+", text))


def _fact(row: tuple) -> dict:
    return {"id": row[0], "subject": row[1], "content": row[2], "created": row[3]}


class Memory:
    def __init__(self, path: Path,
                 clock: Callable[[], datetime] = lambda: datetime.now().astimezone()) -> None:
        """Open (or create) the database at `path`, and its facts table.
        Keep `path` as self.path: the tools and the REPL report it."""
        self.path = Path(path)
        self.clock = clock

        # self.conn, not a local: every method below uses this connection.
        # check_same_thread=False: a gateway may answer on another thread than
        # the one that built Junot. Junot.respond holds a lock, so only one
        # turn at a time ever uses this connection.
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        # Step 12: your notes and chat log, readable by you only.
        os.chmod(self.path, 0o600)
        self.conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS facts USING fts5(subject, content, created UNINDEXED)")
        # Step 7. IF NOT EXISTS is the whole migration: a state.db from step 5
        # gains these two tables and keeps its facts untouched.
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS chat_log (id INTEGER PRIMARY KEY, created TEXT NOT NULL, "
            "user TEXT NOT NULL, assistant TEXT NOT NULL, consolidated INTEGER NOT NULL DEFAULT 0)")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS episodes (id INTEGER PRIMARY KEY, date TEXT NOT NULL, "
            "summary TEXT NOT NULL)")
        self.conn.commit()

    def add(self, subject: str, content: str) -> int:
        """Store one fact. Returns its id."""
        # ? parameters, never an f-string: the values can hold any text,
        # apostrophes and SQL included, and are stored exactly as given.
        cursor = self.conn.execute(
            "INSERT INTO facts (subject, content, created) VALUES (?, ?, ?)",
            (subject, content, self.clock().isoformat()))
        self.conn.commit()
        return cursor.lastrowid

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """The best-matching facts first, at most `limit`. Each is
        {"id", "subject", "content", "created"}. Never raises on odd text."""
        match = fts_query(query)
        if not match:
            return []
        rows = self.conn.execute(
            f"SELECT {COLUMNS} FROM facts WHERE facts MATCH ? ORDER BY rank LIMIT ?",
            (match, limit))
        return [_fact(row) for row in rows]

    def all(self) -> list[dict]:
        """Every fact, oldest first."""
        return [_fact(row) for row in self.conn.execute(f"SELECT {COLUMNS} FROM facts ORDER BY rowid")]

    # ---- step 13: forget and correct ------------------------------------------

    def get(self, note_id: int) -> dict | None:
        rows = list(self.conn.execute(f"SELECT {COLUMNS} FROM facts WHERE rowid = ?", (note_id,)))
        return _fact(rows[0]) if rows else None

    def forget(self, note_id: int) -> dict | None:
        """Delete one fact for good. Returns what was deleted, or None if
        there was no such note. A real DELETE: not hidden, not flagged."""
        fact = self.get(note_id)
        if fact is not None:
            self.conn.execute("DELETE FROM facts WHERE rowid = ?", (note_id,))
            self.conn.commit()
        return fact

    def correct(self, note_id: int, content: str) -> dict | None:
        """Replace one fact's content, keeping its id and subject. Returns the
        fact as it was before, or None if there was no such note."""
        fact = self.get(note_id)
        if fact is not None:
            self.conn.execute("UPDATE facts SET content = ? WHERE rowid = ?", (content, note_id))
            self.conn.commit()
        return fact

    # ---- step 7: the chat log and episodes ------------------------------------

    def log_exchange(self, user: str, assistant: str) -> int:
        """Store one exchange, not yet consolidated. Returns its id."""
        cursor = self.conn.execute(
            "INSERT INTO chat_log (created, user, assistant) VALUES (?, ?, ?)",
            (self.clock().isoformat(), user, assistant))   # consolidated takes its default, 0
        self.conn.commit()
        return cursor.lastrowid

    def unconsolidated(self) -> list[dict]:
        """Exchanges not yet consolidated, oldest first. Each is
        {"id", "created", "user", "assistant"}."""
        rows = self.conn.execute(
            "SELECT id, created, user, assistant FROM chat_log WHERE consolidated = 0 ORDER BY id")
        return [{"id": r[0], "created": r[1], "user": r[2], "assistant": r[3]} for r in rows]

    def mark_consolidated(self, ids: list[int]) -> None:
        """Mark these exchanges as consolidated."""
        # executemany runs the statement once per tuple: (i,) is a one-value tuple.
        self.conn.executemany("UPDATE chat_log SET consolidated = 1 WHERE id = ?", [(i,) for i in ids])
        self.conn.commit()

    def add_episode(self, date: str, summary: str) -> int:
        """Store one episode. Returns its id."""
        cursor = self.conn.execute("INSERT INTO episodes (date, summary) VALUES (?, ?)", (date, summary))
        self.conn.commit()
        return cursor.lastrowid

    def episodes(self) -> list[dict]:
        """Every episode, oldest first. Each is {"id", "date", "summary"}."""
        rows = self.conn.execute("SELECT id, date, summary FROM episodes ORDER BY id")
        return [{"id": r[0], "date": r[1], "summary": r[2]} for r in rows]

    def close(self) -> None:
        self.conn.close()
