"""OpenRouter LLM: question phrasing + factual grading. Jabir — Task C.

OpenAI-compatible: POST https://openrouter.ai/api/v1/chat/completions with
`Authorization: Bearer <key>`. Keep both calls short and low-timeout — they sit
in the live demo's critical path.
"""

from __future__ import annotations

from app.config import Settings


class OpenRouterLlm:
    """Implements contracts.interfaces.Llm."""

    def __init__(self, settings: Settings) -> None:
        raise NotImplementedError("engine/llm.py — Jabir")

    def phrase_question(self, memory_text: str) -> str:
        """Natural, specific question grounded in the memory — without leaking it."""
        raise NotImplementedError

    def factual_check(self, answer: str, memory_text: str) -> bool:
        """Strict: vague or hedged answers are False. This is what catches clones."""
        raise NotImplementedError
