"""Settings, read from the environment and an optional .env file.

A ten-line .env reader instead of python-dotenv: one less dependency, and you
can see exactly what it does. Real environment variables win over .env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str
    base_url: str = GEMINI_BASE_URL
    # A cheaper, faster model for narrow one-shot decisions (the retrieval gate).
    small_model: str = "gemini-3.5-flash-lite"
    # Where Junot keeps what outlives a turn: SOUL.md now, memory later.
    home: Path = Path.home() / ".junot"


def load_settings() -> Settings:
    load_dotenv()
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        raise SystemExit("GEMINI_API_KEY is not set. Copy .env.example to .env and paste your key.")
    home = Path(os.getenv("JUNOT_HOME", Path.home() / ".junot")).expanduser()
    home.mkdir(parents=True, exist_ok=True)
    return Settings(api_key=key, model=os.getenv("JUNOT_MODEL", "gemini-3.6-flash"),
                    small_model=os.getenv("JUNOT_SMALL_MODEL", "gemini-3.5-flash-lite"), home=home)
