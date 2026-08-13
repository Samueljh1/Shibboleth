"""Shared data models. Phase 0 contract — do not diverge silently.

Every module and every HTTP response uses these shapes. If you need a field,
add it here in a PR titled `contract:` and tell the other person.

Mongo `_id` is exposed as `id` in Python; both names are accepted on input and
`_id` is emitted on `.model_dump(by_alias=True)` so documents round-trip.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SessionStatus = Literal["in_progress", "identified", "rejected"]
MemoryKind = Literal["conversation", "fact", "decision", "event"]

VOICE_DIM = 256  # resemblyzer speaker embedding
EMBED_DIM = 1536  # openai text-embedding-3-small


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _Doc(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class User(_Doc):
    id: str = Field(alias="_id")
    name: str
    profile: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class Voiceprint(_Doc):
    id: str = Field(alias="_id")
    user_id: str
    embedding: list[float]
    enrolled_at: datetime = Field(default_factory=_now)


class MemoryEvent(_Doc):
    id: str = Field(alias="_id")
    user_id: str
    ts: datetime
    kind: MemoryKind = "conversation"
    text: str
    salient_attrs: dict = Field(default_factory=dict)
    embedding: list[float] = Field(default_factory=list)


class QuestionSpec(_Doc):
    """A question the engine has chosen to ask."""

    memory_id: str
    owner_id: str  # candidate whose memory this question is drawn from
    target_attr: str | None = None
    ig: float = 0.0  # expected information gain, bits
    question_text: str


class AskedQuestion(_Doc):
    """One completed turn, appended to AuthSession.asked."""

    q: str
    memory_id: str
    owner_id: str
    target_attr: str | None = None
    ig: float = 0.0
    answer: str | None = None
    graded: bool = False
    correct: bool | None = None
    entropy_after: float | None = None


class AuthSession(_Doc):
    id: str = Field(alias="_id")
    candidate_ids: list[str] = Field(default_factory=list)
    posterior: dict[str, float] = Field(default_factory=dict)
    entropy_bits: float = 0.0
    asked: list[AskedQuestion] = Field(default_factory=list)
    status: SessionStatus = "in_progress"
    claimed_id: str | None = None
    pending: "QuestionSpec | None" = None  # question handed out, awaiting an answer
    voice_vec: list[float] = Field(default_factory=list)  # for voice-continuity checks
    created_at: datetime = Field(default_factory=_now)

    @property
    def leader(self) -> tuple[str | None, float]:
        """(user_id, probability) of the current top candidate."""
        if not self.posterior:
            return None, 0.0
        uid = max(self.posterior, key=self.posterior.__getitem__)
        return uid, self.posterior[uid]
