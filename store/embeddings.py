"""Text embeddings via MongoDB Atlas (Voyage models). Sam.

    POST https://ai.mongodb.com/v1/embeddings
    Authorization: Bearer <voyage key>
    {"input": [...], "model": "voyage-3.5-lite", "input_type": "document"}

The endpoint is OpenAI-shaped, so EMBED_BASE_URL can be repointed at any
compatible provider (OpenRouter's /v1/embeddings works) by changing env only --
no code change. That is the fallback if the Voyage key doesn't land in time.
"""

from __future__ import annotations

import requests

from app.config import Settings

TIMEOUT = 30


class VoyageEmbedder:
    """Implements contracts.interfaces.Embedder."""

    def __init__(self, settings: Settings) -> None:
        if not settings.embed_api_key:
            raise RuntimeError("EMBED_API_KEY is not set")
        self.url = settings.embed_base_url.rstrip("/") + "/embeddings"
        self.model = settings.embed_model
        self.dim = settings.embed_dim
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {settings.embed_api_key}",
            "Content-Type": "application/json",
        })

    def _post(self, texts: list[str], input_type: str) -> list[list[float]]:
        body: dict = {"input": texts, "model": self.model}
        if self.model.startswith("voyage"):
            # These are Voyage-only knobs; other providers 400 on them.
            body["input_type"] = input_type
            body["output_dimension"] = self.dim
        r = self.session.post(self.url, json=body, timeout=TIMEOUT)
        if r.status_code != 200:
            raise RuntimeError(f"embeddings {r.status_code}: {r.text[:300]}")
        data = sorted(r.json()["data"], key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in data]

    def embed_text(self, s: str) -> list[float]:
        """A user's spoken answer -- an ad-hoc query against stored memories."""
        return self._post([s or " "], "query")[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Seeding / enrollment -- one call per persona instead of twenty."""
        if not texts:
            return []
        out: list[list[float]] = []
        for i in range(0, len(texts), 128):  # stay under the batch limit
            out.extend(self._post([t or " " for t in texts[i : i + 128]], "document"))
        return out
