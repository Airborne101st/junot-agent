"""The tool registry: every tool the model can call, in one place.

A tool is a name and description the model reads, a JSON Schema for its
arguments, and a Python function that runs. The registry turns them into the
API's `tools=` list, and runs a call safely: whatever goes wrong comes back
as text the model can read, never as an exception that ends the turn.

YOUR CODE (step 2). See docs/steps/02-the-harness.md.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
import json
import threading

# How long a tool may run before the model is told it timed out (step 11).
DEFAULT_TOOL_TIMEOUT = 10.0


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]   # a JSON Schema object, as in step 1
    fn: Callable[..., str]
    timeout: float = DEFAULT_TOOL_TIMEOUT   # seconds

    def to_api(self) -> dict[str, Any]:
        """The OpenAI-shape schema this tool sends in `tools=`."""
        return {
                "type": "function",
                 "function":
                     {
                         "name": self.name,
                         "description": self.description,
                         "parameters": self.parameters,
                     }
                }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        """Every tool's to_api(), in the order they were registered."""
        tools = self._tools.values()
        return [tool.to_api() for tool in tools]

    def execute(self, name: str, arguments: str) -> str:
        """Run one call. `arguments` is the model's JSON string, unparsed.

        Never raises. An unknown tool, arguments that aren't valid JSON,
        arguments the function doesn't accept, and an exception inside the
        function each return a string starting with "Error" that names the
        tool and says what went wrong.
        """
        tool = self.get(name)
        if not tool:
            return f'Error: Unknown tool {name}'

        try:
            args = json.loads(arguments)
        except json.JSONDecodeError as e:
            return f'Error: Invalid JSON arguments: {arguments} for tool:{name}, Error - {e}'

        # Step 11: run the tool on a worker thread and wait at most tool.timeout.
        # try/except catches what a tool raises; a tool that hangs raises
        # nothing, and without this it would block the turn forever (the
        # time.sleep(500) experiment). Python can't kill a thread, so a
        # timed-out tool is abandoned, not stopped: it may still finish in the
        # background, and the error says so rather than pretend otherwise.
        result: dict = {}

        def run() -> None:
            try:
                result["output"] = tool.fn(**args)
            except Exception as e:   # caught here, on the worker, and reported below
                result["error"] = e

        worker = threading.Thread(target=run, daemon=True)   # daemon: never keeps Junot from quitting
        worker.start()
        worker.join(tool.timeout)
        if worker.is_alive():
            return (f'Error: {name} timed out after {tool.timeout:g}s and was abandoned '
                    f'(it may still finish in the background). Tell the user it did not complete.')
        if "error" in result:
            return f'Error: Failed call on tool {name}, arguments: {arguments}, Error - {result["error"]}'
        return result["output"]