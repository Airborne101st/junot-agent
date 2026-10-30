"""Step 12: trace privacy. Owner-only files, retention, and no secrets.

    uv run pytest tests/test_step12_privacy.py -v

Your step 4 answer: "it can be leaked". Before this step every trace was
-rw-r--r-- (any account on the Mac could read it), kept forever, and held
whatever you typed, passwords included.
"""

from __future__ import annotations

import json
import stat
from datetime import datetime, timedelta, timezone

from junot.memory import Memory
from junot.observe import MASK, Tracer, redact

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _lines(folder) -> list[dict]:
    return [json.loads(line) for line in (folder / "2026-10-30.jsonl").read_text(encoding="utf-8").splitlines()]


# ---- owner-only ----------------------------------------------------------------

def test_a_new_trace_file_and_its_folder_are_yours_only(tmp_path):
    folder = tmp_path / "traces"
    tracer = Tracer(folder, clock=lambda: NOW)
    tracer.start_turn("hi")
    assert _mode(folder) == 0o700
    assert _mode(folder / "2026-10-30.jsonl") == 0o600


def test_old_world_readable_traces_are_fixed_at_start(tmp_path):
    folder = tmp_path / "traces"
    folder.mkdir(mode=0o755)
    old = folder / "2026-10-29.jsonl"
    old.write_text("{}\n")
    old.chmod(0o644)
    Tracer(folder, clock=lambda: NOW)
    assert _mode(folder) == 0o700 and _mode(old) == 0o600


def test_the_notes_database_is_yours_only(tmp_path):
    Memory(tmp_path / "state.db").close()
    assert _mode(tmp_path / "state.db") == 0o600


# ---- retention -----------------------------------------------------------------------

def _day_file(folder, days_ago: int):
    path = folder / f"{(NOW - timedelta(days=days_ago)):%Y-%m-%d}.jsonl"
    path.write_text("{}\n")
    return path


def test_traces_older_than_the_limit_are_deleted_at_start(tmp_path):
    folder = tmp_path / "traces"
    folder.mkdir()
    old, edge, recent = _day_file(folder, 31), _day_file(folder, 30), _day_file(folder, 2)
    Tracer(folder, clock=lambda: NOW, keep_days=30)
    assert not old.exists()
    assert edge.exists() and recent.exists(), "30 days ago is still kept"


def test_zero_keeps_everything(tmp_path):
    folder = tmp_path / "traces"
    folder.mkdir()
    ancient = _day_file(folder, 900)
    Tracer(folder, clock=lambda: NOW, keep_days=0)
    assert ancient.exists()


def test_files_that_arent_traces_are_never_deleted(tmp_path):
    folder = tmp_path / "traces"
    folder.mkdir()
    notes = folder / "my-notes.jsonl"
    notes.write_text("{}\n")
    Tracer(folder, clock=lambda: NOW, keep_days=1)
    assert notes.exists()


# ---- redaction ---------------------------------------------------------------------------

def test_a_secret_argument_in_a_tool_call_is_masked(tmp_path):
    """Tool arguments are a JSON *string*, so masking by dict key alone misses them."""
    tracer = Tracer(tmp_path, clock=lambda: NOW)
    tracer.start_turn("log in")
    tracer("tool", {"name": "login", "arguments": '{"user": "akshat", "password": "hunter2"}',
                    "output": "ok", "ok": True, "duration_ms": 3})
    line = _lines(tmp_path)[1]
    assert "hunter2" not in line["arguments"]
    assert "akshat" in line["arguments"], "only the secret goes"


def test_a_password_you_typed_is_masked_in_the_trace(tmp_path):
    tracer = Tracer(tmp_path, clock=lambda: NOW)
    tracer.start_turn("Remember my wifi password is Tr0ub4dor&3 please")
    assert "Tr0ub4dor" not in _lines(tmp_path)[0]["user"]
    assert "wifi password is" in _lines(tmp_path)[0]["user"]


def test_api_keys_and_bot_tokens_are_masked_anywhere():
    text = ("gemini AIzaSyA1234567890abcdefghijklmnopqrstuv, openai sk-abcdefghijklmnopqrstuvwx, "
            "telegram 123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw, header Bearer abcdef1234567890xyz")
    masked = redact(text)
    for secret in ("AIzaSyA1234567890", "sk-abcdefgh", "AAHdqTcvCH1vGWJ", "abcdef1234567890xyz"):
        assert secret not in masked, secret
    assert masked.count(MASK) == 4


def test_secret_keys_in_a_dict_are_masked_whatever_the_value():
    assert redact({"api_key": "short", "Authorization": "anything", "name": "Junot"}) == \
        {"api_key": MASK, "Authorization": MASK, "name": "Junot"}


def test_ordinary_text_and_token_counts_are_left_alone():
    """Masking must not eat the receipt: input_tokens is a count, not a secret."""
    event = {"input_tokens": 742, "output_tokens": 80, "reply": "Your brother's birthday is June 20. Spin is fun.",
             "query": "brother birthday"}
    assert redact(event) == event


def test_the_trace_still_has_what_debugging_needs(tmp_path):
    tracer = Tracer(tmp_path, clock=lambda: NOW)
    tracer.start_turn("Time in Tokyo?")
    tracer("tool", {"name": "get_time", "arguments": '{"timezone": "Asia/Tokyo"}',
                    "output": "2026-10-30T12:30:00+09:00", "ok": True, "duration_ms": 0})
    tool = _lines(tmp_path)[1]
    assert tool["arguments"] == '{"timezone": "Asia/Tokyo"}' and tool["output"] == "2026-10-30T12:30:00+09:00"
