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
    "- GIVE THE SPEAKER A WAY IN. Anchor the question in when it happened and "
    "name the general area it was about -- the kind of thing, never the thing "
    "itself. 'Yesterday afternoon you changed how your search works -- what "
    "did you switch it to?' is right: it locates the memory and still makes "
    "them supply the answer. 'What do you remember from yesterday?' is wrong: "
    "nobody can answer that. A question they cannot place is as useless as one "
    "that gives the answer away.\n"
    "- The hint may name the CATEGORY (search, your commute, a pet, a meal, a "
    "delivery) but never the ANSWER (which search method, which route, the "
    "pet's name, what you ate, what arrived).\n"
    "- MUST be an open question that forces the speaker to supply the detail. "
    "Begin with What, Which, Who, Where, When or How.\n"
    "- NEVER ask a yes/no question. Do not begin with Did, Do, Was, Were, Is, "
    "Are, Have, Has, Had, Can, Could, Would, Will or Should. A yes/no question "
    "is useless here: 'yes' proves nothing and cannot be graded.\n"
    "- One sentence, under 20 words, natural spoken English.\n"
    "- Output the question only. No preamble, no quotes."
)

_YES_NO_OPENERS = (
    "did", "do", "does", "was", "were", "is", "are", "have", "has", "had",
    "can", "could", "would", "will", "should", "am",
)


def is_yes_no(question: str) -> bool:
    """A closed question cannot elicit a gradeable specific -- reject it.

    This is the bug that false-rejected a genuine user on stage: asked "Did you
    feel differently after reading that essay?", they answered truthfully and
    conversationally, the grader found none of the memory's specifics in it, and
    marked NO. The question never asked for a specific.
    """
    first = (question or "").strip().lstrip("\"'").split(" ")[0].strip(",.?!").lower()
    return first in _YES_NO_OPENERS

_GRADE_SYSTEM = (
    "You grade whether an ANSWER shows the speaker genuinely remembers a stored "
    "MEMORY. You are given the QUESTION that was asked.\n"
    "Reply with exactly one word: YES or NO.\n"
    "Judge the answer against WHAT THE QUESTION ASKED FOR. Do not demand a "
    "detail the question never requested.\n"
    "YES if the answer is consistent with the memory and adds something only "
    "someone who lived it would say — the right decision, person, place, "
    "number, outcome, reason or feeling. Partial recall is YES: real people "
    "recall the gist and paraphrase. Casual, conversational phrasing is YES.\n"
    "NO if it contradicts the memory, says 'I don't remember', or is so generic "
    "it would fit almost anyone's week. A bare 'yes' or 'no' with nothing else "
    "is NO — it carries no evidence either way."
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

    def factual_check(
        self, answer: str, memory_text: str, question: str | None = None
    ) -> bool:
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
