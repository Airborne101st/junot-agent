"""The model client: the OpenAI SDK pointed at Gemini.

Gemini speaks the OpenAI Chat Completions dialect at GEMINI_BASE_URL, so the
loop is written against that one shape. Switching to OpenAI, OpenRouter or a
local model later is a base_url and a key, not a rewrite.

Run this module to list the models your key can use:
    uv run python -m junot.client
"""

from __future__ import annotations

from openai import OpenAI

from junot.config import Settings, load_settings


def get_client(settings: Settings) -> OpenAI:
    # Step 11: the SDK waits up to 10 minutes per call and retries twice. A
    # hung call would hold the turn (and, through the lock, every gateway)
    # for half an hour. One retry, and a deadline from the settings.
    return OpenAI(api_key=settings.api_key, base_url=settings.base_url,
                  timeout=settings.model_timeout, max_retries=1)


if __name__ == "__main__":
    for model in get_client(load_settings()).models.list():
        print(model.id)
