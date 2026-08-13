"""Protocols every module programs against. Phase 0 contract.

Modules never import each other — they import these Protocols and receive a
concrete implementation by injection (see app/deps.py). That is what lets the
two of us build in parallel without stepping on each other.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from contracts.models import AuthSession, MemoryEvent, QuestionSpec, User


@runtime_checkable
class Embedder(Protocol):
    def embed_text(self, s: str) -> list[float]: ...


@runtime_checkable
class VoiceEncoder(Protocol):
    def embed_voice(self, audio: bytes) -> list[float]: ...


@runtime_checkable
class Stt(Protocol):
    def transcribe(self, audio: bytes) -> str: ...


@runtime_checkable
class Tts(Protocol):
    """Optional. When no TTS is wired, questions render as text only."""

    def speak(self, text: str) -> bytes: ...


@runtime_checkable
class Llm(Protocol):
    def phrase_question(self, memory_text: str) -> str:
        """Turn a memory into a natural question that does NOT leak its answer."""
        ...

    def factual_check(self, answer: str, memory_text: str) -> bool:
        """True if `answer` is factually consistent with `memory_text`."""
        ...


@runtime_checkable
class Store(Protocol):
    def narrow(self, voice_vec: list[float], k: int) -> list[tuple[str, float]]:
        """Top-k (user_id, cosine_similarity) by voiceprint vector search."""
        ...

    def memories(self, user_id: str) -> list[MemoryEvent]: ...

    def get_user(self, user_id: str) -> User: ...

    def list_users(self) -> list[User]: ...

    def wipe_user_memory(self, user_id: str) -> None:
        """Delete all memory_events for a user — powers the live wipe demo beat."""
        ...

    def save_session(self, session: AuthSession) -> None: ...

    def get_session(self, session_id: str) -> AuthSession | None: ...


@runtime_checkable
class Engine(Protocol):
    def start(self, candidates: list[tuple[str, float]]) -> AuthSession: ...

    def next_question(self, s: AuthSession) -> tuple[AuthSession, QuestionSpec | None]:
        """Choose the highest-expected-information-gain question.

        Returns `(session, None)` when no question can be asked — budget spent,
        or no candidate has any memory left (the post-wipe demo path). The
        caller finalises the session in that case.
        """
        ...

    def grade_and_update(
        self, s: AuthSession, q: QuestionSpec, answer: str
    ) -> AuthSession: ...

    def finalize(self, s: AuthSession, force: bool = False) -> AuthSession:
        """Apply the stop rules and set `status`. `force=True` ends it outright.

        Called by the API when `next_question` returns None, so the stop policy
        lives in one place (the engine) rather than leaking into app/main.py.
        """
        ...
