"""Text embeddings via OpenAI. Sam."""

from __future__ import annotations

from openai import OpenAI

from app.config import Settings


class OpenAIEmbedder:
    """Implements contracts.interfaces.Embedder."""

    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.embed_model

    def embed_text(self, s: str) -> list[float]:
        r = self.client.embeddings.create(model=self.model, input=s or " ")
        return r.data[0].embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Seeding path — one call for a whole persona instead of 20."""
        r = self.client.embeddings.create(model=self.model, input=texts or [" "])
        return [d.embedding for d in r.data]
