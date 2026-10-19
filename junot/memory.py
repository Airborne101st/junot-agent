"""Long-term memory: facts that survive a restart, in one SQLite file.

Working memory (session.py) is gone when the REPL closes. This is the other
kind: a table of short facts in <home>/state.db, searched by keyword with
SQLite's built-in full-text index, FTS5. No embeddings, no server, nothing to
install. Open the file with `sqlite3 data/state.db` and read every fact.

YOUR CODE (step 5). See docs/steps/05-memory.md.
"""

from __future__ import annotations

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
        self.conn = sqlite3.connect(self.path)
        self.conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS facts USING fts5(subject, content, created UNINDEXED)")
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

    def close(self) -> None:
        self.conn.close()
