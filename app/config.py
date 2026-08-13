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
    mongo_password: str = field(default_factory=lambda: _s("MONGO_PASSWORD"))
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
    # Embeddings: MongoDB Atlas (Voyage) by default; OpenAI-shaped, so
    # EMBED_BASE_URL can be repointed at any compatible provider.
    embed_base_url: str = field(
        default_factory=lambda: _s("EMBED_BASE_URL", "https://ai.mongodb.com/v1")
    )
    embed_api_key: str = field(default_factory=lambda: _s("EMBED_API_KEY"))
    embed_model: str = field(default_factory=lambda: _s("EMBED_MODEL", "voyage-3.5-lite"))
    embed_dim: int = field(default_factory=lambda: _i("EMBED_DIM", 1024))

    # Engine (Jabir)
    tau_id: float = field(default_factory=lambda: _f("TAU_ID", 0.85))
    tau_reject: float = field(default_factory=lambda: _f("TAU_REJECT", 0.05))
    max_questions: int = field(default_factory=lambda: _i("MAX_QUESTIONS", 5))
    voice_topk: int = field(default_factory=lambda: _i("VOICE_TOPK", 8))


def _resolve_uri(s: Settings) -> Settings:
    """Atlas hands you a URI with a <db_password> placeholder. Keep the secret
    in its own env var so the URI itself stays paste-able and shareable."""
    if s.mongodb_uri and "<db_password>" in s.mongodb_uri:
        if not s.mongo_password:
            return s  # AtlasStore will report the missing password
        from urllib.parse import quote_plus

        object.__setattr__(
            s, "mongodb_uri",
            s.mongodb_uri.replace("<db_password>", quote_plus(s.mongo_password)),
        )
    return s


settings = _resolve_uri(Settings())
