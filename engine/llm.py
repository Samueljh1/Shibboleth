"""OpenRouter LLM: question phrasing + factual grading. Jabir — Task C.

OpenAI-compatible: POST https://openrouter.ai/api/v1/chat/completions with
`Authorization: Bearer <key>`. Both calls sit in the live demo's critical path,
so they are short, low-temperature and low-timeout.

Failure policy differs per call, on purpose:

  * `phrase_question` returns "" when anything goes wrong — the engine then
    asks a safe templated question and the demo keeps moving;
  * `factual_check` RAISES. The engine catches it and grades on embedding
    similarity alone. Returning False on a timeout would mark a genuine user's
    correct answer wrong and false-reject them on stage.
"""

from __future__ import annotations

import requests

from app.config import Settings

API_URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT = 12.0

_PHRASE_SYSTEM = (
    "You write ONE short spoken-style question that verifies whether the "
    "speaker personally lived a given memory.\n"
    "Rules:\n"
    "- NEVER restate the memory's specifics. The question must not contain the "
    "answer: no names, numbers, places or decisions taken from the memory.\n"
    "- Refer to it obliquely by time and context ('yesterday afternoon', "
    "'on your commute') so only someone who was there can answer.\n"
    "- One sentence, under 20 words, natural spoken English.\n"
    "- Output the question only. No preamble, no quotes."
)

_GRADE_SYSTEM = (
    "You grade whether an ANSWER is consistent with a stored MEMORY the "
    "speaker should personally recall.\n"
    "Reply with exactly one word: YES or NO.\n"
    "YES only if the answer matches the memory's specifics (the right "
    "decision, person, place, number or outcome).\n"
    "NO if it is vague, hedged, generic, evasive, says 'I don't remember', or "
    "contradicts the memory. Plausible-sounding but unspecific is NO — an "
    "impostor's answer sounds exactly like that."
)


class OpenRouterLlm:
    """Implements contracts.interfaces.Llm."""

    def __init__(self, settings: Settings) -> None:
        if not settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        self.model = settings.openrouter_model
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "Content-Type": "application/json",
                # OpenRouter attributes traffic with these; harmless if absent.
                "HTTP-Referer": "https://github.com/shibboleth",
                "X-Title": "Shibboleth",
            }
        )

    def phrase_question(self, memory_text: str) -> str:
        """Natural, specific question grounded in the memory — without leaking it."""
        try:
            out = self._chat(_PHRASE_SYSTEM, f"MEMORY: {memory_text}", max_tokens=60)
        except Exception:
            return ""  # engine falls back to a templated question
        return out.strip().strip('"').splitlines()[0] if out.strip() else ""

    def factual_check(self, answer: str, memory_text: str) -> bool:
        """Strict: vague or hedged answers are False. This is what catches clones.

        Raises on transport failure — see the module docstring.
        """
        out = self._chat(
            _GRADE_SYSTEM,
            f"MEMORY: {memory_text}\nANSWER: {answer}",
            max_tokens=3,
        )
        return out.strip().upper().startswith("Y")

    # -- internals ---------------------------------------------------------

    def _chat(self, system: str, user: str, max_tokens: int) -> str:
        r = self.session.post(
            API_URL,
            json={
                "model": self.model,
                "temperature": 0.2,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""
