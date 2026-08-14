"""Question phrasing support: attribute targeting, leak detection, fallbacks.
Jabir — Task C.

A question that leaks its own answer ("You switched the retriever to hybrid
rankFusion on Tuesday — what did you switch the retriever to?") is worse than
useless: the impostor answers it correctly and the posterior concentrates on
the wrong person. So every LLM-phrased question passes a leak check before it
is asked, and there is always a safe template to fall back to when the LLM is
slow, down, or careless.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from contracts.models import MemoryEvent

_WORD = re.compile(r"[a-z0-9']+")

_STOP = {
    "about", "after", "again", "also", "back", "because", "been", "before",
    "being", "both", "came", "come", "could", "does", "doing", "done", "down",
    "each", "even", "every", "from", "gave", "gets", "give", "going", "gone",
    "good", "have", "having", "here", "into", "just", "keep", "kept", "know",
    "last", "like", "made", "make", "many", "more", "most", "much", "must",
    "need", "next", "only", "other", "over", "really", "said", "same", "says",
    "should", "since", "some", "still", "such", "take", "than", "that", "their",
    "them", "then", "there", "these", "they", "thing", "things", "this", "those",
    "through", "time", "told", "took", "very", "want", "well", "went", "were",
    "what", "when", "where", "which", "while", "will", "with", "would", "your",
    "yours",
}

_NUMBER = re.compile(r"\d[\d,.:]*")
_NUMBER_WORDS = {
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty",
    "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "dozen",
    "first", "second", "third", "fourth", "fifth", "sixth", "seventh",
    "eighth", "ninth", "tenth", "twice", "half",
}
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

LEAK_TOKEN_RATIO = 0.6
"""Share of a memory's distinctive tokens that, if echoed, counts as a leak."""

LEAK_NGRAM = 6
"""A verbatim run this long lifted from the memory is a leak on its own."""


def content_tokens(text: str) -> list[str]:
    """Distinctive lowercase tokens — the bits an answer would have to supply."""
    return [t for t in _WORD.findall((text or "").lower()) if len(t) > 3 and t not in _STOP]


def _distinctive_marks(text: str, include_initial: bool = False) -> set[str]:
    """Proper nouns and numbers — the tokens that ARE the answer.

    Asymmetric on purpose. On the QUESTION side sentence-initial words are
    skipped: "What"/"Did" are capitalised by position and would flag every
    question. On the MEMORY side they are kept (`include_initial`), because a
    name that happens to open a sentence -- "Roscoe barked at the truck" -- is
    still a name, and missing it let a question cue the answer by naming it. A
    false positive here only costs us a templated question, which is safe.
    """
    t = text or ""
    marks = {m.group(0).lower() for m in _NUMBER.finditer(t)}
    # Spelled-out numbers count too: "is it six?" leaks exactly as "is it 6?".
    marks |= {w for w in _WORD.findall(t.lower()) if w in _NUMBER_WORDS}
    for sentence in _SENTENCE.split(t):
        words = sentence.split()
        for w in (words if include_initial else words[1:]):
            bare = w.strip(".,;:!?\"'()[]")
            if len(bare) > 2 and bare[0].isupper() and not bare.isupper():
                marks.add(bare.lower())
    return marks


def leaks_answer(
    question: str,
    memory_text: str,
    token_ratio: float = LEAK_TOKEN_RATIO,
    ngram: int = LEAK_NGRAM,
) -> bool:
    """True if the question hands over the memory's content.

    The ratio test alone is too permissive in practice: "Did you feel the
    excitement when Priya joined the team?" echoes one token out of twenty and
    scores ~0.05, yet it hands an impostor the entire answer. A single shared
    proper noun or number IS the answer, so those are checked outright before
    the ratio.
    """
    distinct = set(content_tokens(memory_text))
    if not distinct:
        return False

    # Proper nouns and numbers: any single one shared is a leak.
    mem_marks = _distinctive_marks(memory_text, include_initial=True)
    if mem_marks & _distinctive_marks(question):
        return True

    if len(distinct & set(content_tokens(question))) / len(distinct) >= token_ratio:
        return True

    words = (memory_text or "").lower().split()
    q_lower = " ".join((question or "").lower().split())
    return any(
        " ".join(words[i : i + ngram]) in q_lower
        for i in range(max(0, len(words) - ngram + 1))
    )


def pick_target_attr(
    memory: MemoryEvent,
    memories_by_candidate: dict[str, list[MemoryEvent]],
    owner_id: str,
) -> str | None:
    """Name the salient attribute this question actually discriminates on.

    Prefers a key where the other candidates are known to hold *different*
    values — that attribute is the one doing the identifying work, and it is
    what the UI labels the step with.
    """
    attrs = dict(memory.salient_attrs or {})
    if not attrs:
        return None

    best_key, best_spread = None, -1
    for key, own_value in attrs.items():
        others = set()
        for uid, mems in memories_by_candidate.items():
            if uid == owner_id:
                continue
            for m in mems:
                v = (m.salient_attrs or {}).get(key)
                if v is not None:
                    others.add(_hashable(v))
        spread = len(others - {_hashable(own_value)})
        if spread > best_spread:
            best_key, best_spread = key, spread
    return best_key


def _hashable(v):
    if isinstance(v, (list, tuple)):
        return tuple(_hashable(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted((k, _hashable(x)) for k, x in v.items()))
    return v


def when_phrase(ts, now: datetime | None = None) -> str:
    """Human, demo-friendly recency: 'yesterday afternoon', 'on Tuesday'.

    Recency is the cue that makes the question answerable by the real person
    and unanswerable by a clone, so it belongs in the wording.
    """
    if not isinstance(ts, datetime):
        return "recently"
    now = now or datetime.now(ts.tzinfo or timezone.utc)
    try:
        delta = now - ts
    except TypeError:  # naive/aware mismatch
        ts, now = ts.replace(tzinfo=None), now.replace(tzinfo=None)
        delta = now - ts

    hours = delta.total_seconds() / 3600.0
    part = _day_part(ts)
    if hours < 0:
        return "just now"
    if hours < 12:
        return "late last night" if part == "night" else f"earlier {part}"
    if hours < 36:
        return f"yesterday {part}"
    if hours < 24 * 7:
        return f"on {ts.strftime('%A')}"
    if hours < 24 * 30:
        return "a couple of weeks ago"
    return "a while back"


def _day_part(ts: datetime) -> str:
    h = ts.hour
    if h < 5:
        return "night"
    if h < 12:
        return "morning"
    if h < 17:
        return "afternoon"
    return "evening"


_TEMPLATES = {
    "conversation": "Who were you talking to {when}, and what was it about?",
    "decision": "You made a call on something {when}. What did you decide, and why?",
    "fact": "There's something you told me {when}. What was it?",
    "event": "Something happened {when} — what was it?",
}


def fallback_question(memory: MemoryEvent, target_attr: str | None = None) -> str:
    """A safe, non-leaking question. Used when the LLM is absent or leaked.

    Deliberately vague about content and specific about time: the timestamp is
    the cue, the content is what the speaker has to supply.
    """
    when = when_phrase(memory.ts)
    if target_attr:
        attr = str(target_attr).replace("_", " ").strip()
        # "Thinking back to {when}" double-prepositioned ("to on Tuesday") and
        # "what was your producer?" reads as nonsense. Lead with the time, use
        # the attribute as the HINT, and still make them supply the detail.
        return (
            f"{when[:1].upper()}{when[1:]} you mentioned something "
            f"about your {attr} — what exactly was it?"
        )
    template = _TEMPLATES.get((memory.kind or "").lower(), "What do you remember from {when}?")
    return template.format(when=when)
