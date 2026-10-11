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
    return OpenAI(api_key=settings.api_key, base_url=settings.base_url)


if __name__ == "__main__":
    for model in get_client(load_settings()).models.list():
        print(model.id)
