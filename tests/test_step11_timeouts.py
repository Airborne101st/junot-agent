"""Step 11: timeouts. try/except catches what raises; a hang raises nothing.

    uv run pytest tests/test_step11_timeouts.py -v
"""

from __future__ import annotations

import json
import threading
import time

from junot.client import get_client
from junot.config import Settings
from junot.loop import run_loop
from junot.registry import DEFAULT_TOOL_TIMEOUT, Tool, ToolRegistry
from tests.fakes import ScriptedClient, reply, tool_call

NO_ARGS = {"type": "object", "properties": {}}


def _registry(fn, timeout: float) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(Tool("slow", "A slow tool.", NO_ARGS, fn, timeout=timeout))
    return registry


def test_a_hanging_tool_returns_an_error_in_about_its_timeout():
    """The time.sleep(500) experiment from step 2, now with an answer."""
    release = threading.Event()
    registry = _registry(lambda: release.wait(30) and "finished", timeout=0.2)
    started = time.perf_counter()
    out = registry.execute("slow", "{}")
    elapsed = time.perf_counter() - started
    release.set()
    assert out.startswith("Error") and "slow" in out and "timed out" in out
    assert elapsed < 1.0, f"it took {elapsed:.1f}s"


def test_a_timed_out_tool_says_honestly_that_it_may_still_run():
    release = threading.Event()
    out = _registry(lambda: release.wait(30) and "x", timeout=0.1).execute("slow", "{}")
    release.set()
    assert "background" in out, "Python can't stop the thread: don't claim it was stopped"


def test_a_fast_tool_is_unaffected():
    assert _registry(lambda: "done", timeout=0.5).execute("slow", "{}") == "done"


def test_an_exception_inside_the_tool_is_still_an_error_string():
    def boom():
        raise RuntimeError("the disk is full")
    out = _registry(boom, timeout=1).execute("slow", "{}")
    assert out.startswith("Error") and "the disk is full" in out


def test_wrong_arguments_are_still_an_error_string():
    out = _registry(lambda: "x", timeout=1).execute("slow", json.dumps({"nope": 1}))
    assert out.startswith("Error") and "slow" in out


def test_tools_get_ten_seconds_by_default():
    assert DEFAULT_TOOL_TIMEOUT == 10
    assert Tool("t", "d", NO_ARGS, lambda: "x").timeout == 10


def test_the_model_reads_the_timeout_and_the_turn_goes_on():
    release = threading.Event()
    registry = _registry(lambda: release.wait(30) and "late", timeout=0.1)
    client = ScriptedClient([reply(tool_calls=[tool_call("slow", {})]), reply("That lookup timed out, sorry.")])
    answer = run_loop(client, "m", [{"role": "user", "content": "go"}], registry)
    release.set()
    assert answer == "That lookup timed out, sorry."
    assert "timed out" in client.calls[1]["messages"][-1]["content"]


def test_model_calls_have_a_deadline_and_one_retry(tmp_path):
    settings = Settings(api_key="x", model="m", home=tmp_path, model_timeout=12.5)
    client = get_client(settings)
    assert client.timeout == 12.5, "the SDK's default is 600 seconds"
    assert client.max_retries == 1


def test_the_default_model_deadline_is_a_minute(tmp_path):
    assert Settings(api_key="x", model="m", home=tmp_path).model_timeout == 60
