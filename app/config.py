"""Env config. Real services only — fill .env before running."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name) or default)
    except ValueError:
        return default


def _s(name: str, default: str = "") -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    # Mongo (Sam)
    mongodb_uri: str = field(default_factory=lambda: _s("MONGODB_URI"))
    atlas_db: str = field(default_factory=lambda: _s("ATLAS_DB", "shibboleth"))
    voice_index: str = field(default_factory=lambda: _s("ATLAS_VOICE_INDEX", "voiceprints_vec"))

    # Voice (Jabir)
    elevenlabs_api_key: str = field(default_factory=lambda: _s("ELEVENLABS_API_KEY"))
    elevenlabs_voice_id: str = field(default_factory=lambda: _s("ELEVENLABS_VOICE_ID"))

    # LLM + embeddings
    openrouter_api_key: str = field(default_factory=lambda: _s("OPENROUTER_API_KEY"))
    openrouter_model: str = field(
        default_factory=lambda: _s("OPENROUTER_MODEL", "anthropic/claude-sonnet-4.5")
    )
    openai_api_key: str = field(default_factory=lambda: _s("OPENAI_API_KEY"))
    embed_model: str = field(default_factory=lambda: _s("EMBED_MODEL", "text-embedding-3-small"))

    # Engine (Jabir)
    tau_id: float = field(default_factory=lambda: _f("TAU_ID", 0.85))
    tau_reject: float = field(default_factory=lambda: _f("TAU_REJECT", 0.05))
    max_questions: int = field(default_factory=lambda: _i("MAX_QUESTIONS", 5))
    voice_topk: int = field(default_factory=lambda: _i("VOICE_TOPK", 8))


settings = Settings()
