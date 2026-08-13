"""In-process stand-ins for Store / Embedder / Llm, so engine/ can be tested
without Atlas, OpenAI or OpenRouter. Jabir — Task C.

`FakeEmbedder` is a hashing vectoriser, NOT random-per-string. That matters: a
"deterministic random vector per string" embedder maps every distinct string to
an orthogonal vector, so `cosine(answer, memory)` is ~0 whether the answer is
right or wrong and the grading path silently tests nothing. Here, overlapping
text really does score high.

The personas below are deliberately hostile to a lazy selector: several pairs
share a near-duplicate memory (the standup pair, the Ethiopian-coffee pair, the
Frankfurt-outage pair), so a question chosen without regard to discriminability
lands on something two candidates can both answer.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timedelta, timezone

from contracts.models import AuthSession, MemoryEvent, User, Voiceprint

_WORD = re.compile(r"[a-z0-9']+")
NOW = datetime(2026, 8, 13, 18, 0, tzinfo=timezone.utc)


# -- Embedder ---------------------------------------------------------------


class FakeEmbedder:
    """Implements contracts.interfaces.Embedder. Signed hashing trick over word
    tokens plus character trigrams; stable across processes (blake2b, never
    Python's salted hash)."""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed_text(self, s: str) -> list[float]:
        vec = [0.0] * self.dim
        counts: dict[str, int] = {}
        for tok in self._tokens(s):
            counts[tok] = counts.get(tok, 0) + 1
        for tok, c in counts.items():
            h = hashlib.blake2b(tok.encode(), digest_size=8).digest()
            n = int.from_bytes(h, "big")
            vec[n % self.dim] += (1.0 if (n >> 63) & 1 else -1.0) * (1.0 + math.log(c))
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec] if norm > 1e-12 else vec

    @staticmethod
    def _tokens(text: str) -> list[str]:
        out: list[str] = []
        for w in _WORD.findall((text or "").lower()):
            out.append(w)
            if len(w) > 4:  # soften plurals/tense so "decided" ~ "decide"
                padded = f"^{w}$"
                out.extend(padded[i : i + 3] for i in range(len(padded) - 2))
        return out


# -- Llm --------------------------------------------------------------------

_STOP = {
    "about", "after", "been", "before", "could", "from", "have", "into", "just",
    "like", "made", "make", "more", "most", "much", "only", "other", "over",
    "said", "same", "some", "such", "than", "that", "their", "them", "then",
    "there", "these", "they", "this", "time", "told", "very", "went", "were",
    "what", "when", "where", "which", "while", "with", "your",
}


def _content(text: str) -> set[str]:
    return {t for t in _WORD.findall((text or "").lower()) if len(t) > 3 and t not in _STOP}


class FakeLlm:
    """Implements contracts.interfaces.Llm. Template phrasing (never leaks) and
    keyword-overlap grading."""

    FACTUAL_RATIO = 0.25

    def phrase_question(self, memory_text: str) -> str:
        t = (memory_text or "").lower()
        if any(w in t for w in ("decid", "chose", "switch", "picked")):
            return "You made a call on this one — what did you decide, and why that way?"
        if any(w in t for w in ("talked", "spoke", "told", "meeting", "standup")):
            return "Who were you talking to, and what actually came out of it?"
        return "What's the specific thing you remember about that?"

    def factual_check(self, answer: str, memory_text: str) -> bool:
        want = _content(memory_text)
        if not want:
            return False
        return len(want & _content(answer)) / len(want) >= self.FACTUAL_RATIO


class DeadLlm(FakeLlm):
    """Both calls fail — proves a dead OpenRouter degrades instead of breaking."""

    def phrase_question(self, memory_text: str) -> str:
        raise RuntimeError("openrouter timeout")

    def factual_check(self, answer: str, memory_text: str) -> bool:
        raise RuntimeError("openrouter timeout")


# -- Store ------------------------------------------------------------------


class FakeStore:
    """Implements contracts.interfaces.Store, in memory."""

    def __init__(self, users, voiceprints, memories) -> None:
        self._users = {u.id: u for u in users}
        self._voiceprints = list(voiceprints)
        self._memories: dict[str, list[MemoryEvent]] = {}
        self._sessions: dict[str, AuthSession] = {}
        for m in memories:
            self._memories.setdefault(m.user_id, []).append(m)

    def narrow(self, voice_vec: list[float], k: int) -> list[tuple[str, float]]:
        best: dict[str, float] = {}
        for vp in self._voiceprints:
            sim = _cosine(voice_vec, vp.embedding)
            if sim > best.get(vp.user_id, -2.0):
                best[vp.user_id] = sim
        return sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:k]

    def memories(self, user_id: str) -> list[MemoryEvent]:
        return [m.model_copy(deep=True) for m in self._memories.get(user_id, [])]

    def get_user(self, user_id: str) -> User:
        return self._users[user_id]

    def list_users(self) -> list[User]:
        return list(self._users.values())

    def wipe_user_memory(self, user_id: str) -> None:
        self._memories.pop(user_id, None)

    def save_session(self, session: AuthSession) -> None:
        self._sessions[session.id] = session

    def get_session(self, session_id: str) -> AuthSession | None:
        return self._sessions.get(session_id)


def _cosine(a, b) -> float:
    if not a or not b:
        return 0.0
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


# -- personas ---------------------------------------------------------------

# uid -> (name, profile, [(kind, text, salient_attrs, hours_ago)])
PERSONAS: dict[str, tuple] = {
    "u_ada": ("Ada", {"role": "founder", "city": "SF"}, [
        ("decision", "Decided to switch the retriever to hybrid rankFusion after recall stalled at sixty one percent.", {"current_project": "Shibboleth"}, 26),
        ("conversation", "Talked to Priya about pulling the Series A timeline forward to October.", {"investor": "Priya"}, 30),
        ("event", "Left my laptop charger at the Blue Bottle on Mint Plaza and borrowed one from the barista.", {"cafe": "Blue Bottle"}, 52),
        ("fact", "The dog walker moved Nutmeg's Thursday slot to eleven in the morning.", {"pet": "Nutmeg"}, 78),
        ("conversation", "Standup ran long again arguing about the deploy freeze.", {"team": "platform"}, 8),
    ]),
    "u_ben": ("Ben", {"role": "infra", "city": "Oakland"}, [
        ("decision", "Chose to shard the events table by tenant rather than by month.", {"current_project": "Ledger"}, 27),
        ("event", "Pager went off at three in the morning for the Frankfurt region latency spike.", {"oncall": "yes"}, 40),
        ("conversation", "Told Marco the migration has to wait until after the security audit.", {"colleague": "Marco"}, 55),
        ("fact", "Started brewing the Ethiopian beans my sister mailed from Portland.", {"coffee": "Ethiopian"}, 80),
        ("conversation", "Standup ran long again arguing about the deploy freeze.", {"team": "platform"}, 9),
    ]),
    "u_cara": ("Cara", {"role": "design", "city": "SF"}, [
        ("decision", "Killed the onboarding carousel and replaced it with a single checklist.", {"current_project": "Atlas UI"}, 28),
        ("event", "Popped a tyre on Valencia and walked the bike eleven blocks home.", {"bike": "Valencia"}, 45),
        ("conversation", "Argued with Jonah about whether the empty state needs an illustration.", {"colleague": "Jonah"}, 60),
        ("fact", "Booked the pottery class for Sunday morning in Bernal Heights.", {"hobby": "pottery"}, 90),
        ("fact", "Started brewing the Ethiopian beans a friend brought back.", {"coffee": "Ethiopian"}, 84),
    ]),
    "u_dev": ("Dev", {"role": "data", "city": "Berkeley"}, [
        ("decision", "Went with DuckDB over Postgres for the offline scoring job.", {"current_project": "Scoring"}, 29),
        ("conversation", "Called my landlord about the leak under the kitchen sink, again.", {"home": "leak"}, 47),
        ("event", "The Frankfurt region latency spike woke half the team up.", {"oncall": "no"}, 41),
        ("fact", "Signed up for the Wednesday bouldering session at Ironworks.", {"hobby": "bouldering"}, 95),
        ("conversation", "Told Priya the eval numbers were inflated by a leak in the split.", {"colleague": "Priya"}, 33),
    ]),
    "u_eve": ("Eve", {"role": "gtm", "city": "SF"}, [
        ("decision", "Cut the enterprise tier from the pricing page until the first quarter.", {"current_project": "Pricing"}, 31),
        ("conversation", "Coffee with Hana turned into a two hour argument about attribution.", {"colleague": "Hana"}, 49),
        ("event", "Missed the flight to Seattle and rebooked onto the red eye.", {"travel": "Seattle"}, 70),
        ("fact", "The new office badge still does not open the fourth floor door.", {"office": "badge"}, 100),
        ("fact", "Picked up the framed print from the shop on Hayes Street.", {"errand": "framing"}, 58),
    ]),
}

SPEAKER_COMMON = 0.62
"""Cross-speaker cosine floor. Real speaker embeddings are NOT near-orthogonal —
any two humans sit around 0.6, the same human around 0.9. Fixtures built from
plain random vectors sit near 0.0, which makes narrowing look miraculous and
would let a badly-tuned prior sail through these tests."""


def _hash_unit_vector(key: bytes, dim: int = 256) -> list[float]:
    seed = hashlib.blake2b(key, digest_size=16).digest()
    vec = [
        (int.from_bytes(hashlib.blake2b(seed + i.to_bytes(2, "big"), digest_size=4).digest(), "big") / 2**32) - 0.5
        for i in range(dim)
    ]
    n = math.sqrt(sum(x * x for x in vec))
    return [x / n for x in vec]


def voice_vector(user_id: str, jitter: float = 0.0) -> list[float]:
    """A stable 256-d pseudo-voiceprint with realistic speaker clustering.

    `jitter` perturbs it deterministically — a second utterance by the same
    speaker, or a clone landing close to its target.
    """
    common = _hash_unit_vector(b"shibboleth-common-speaker-subspace")
    personal = _hash_unit_vector(user_id.encode())
    a, b = SPEAKER_COMMON**0.5, (1.0 - SPEAKER_COMMON) ** 0.5
    vec = [a * c + b * p for c, p in zip(common, personal)]
    if jitter:
        noise = _hash_unit_vector(b"jitter:" + user_id.encode())
        vec = [v + jitter * n for v, n in zip(vec, noise)]
    n = math.sqrt(sum(x * x for x in vec))
    return [x / n for x in vec]


def build_world(embedder: FakeEmbedder | None = None) -> tuple[FakeStore, FakeEmbedder]:
    embedder = embedder or FakeEmbedder()
    users, voiceprints, memories = [], [], []
    for uid, (name, profile, events) in PERSONAS.items():
        users.append(User(_id=uid, name=name, profile=dict(profile)))
        voiceprints.append(Voiceprint(_id=f"vp_{uid}", user_id=uid, embedding=voice_vector(uid)))
        for i, (kind, text, attrs, hours_ago) in enumerate(events):
            memories.append(
                MemoryEvent(
                    _id=f"m_{uid}_{i}",
                    user_id=uid,
                    ts=NOW - timedelta(hours=hours_ago),
                    kind=kind,
                    text=text,
                    salient_attrs=dict(attrs),
                    embedding=embedder.embed_text(text),
                )
            )
    return FakeStore(users, voiceprints, memories), embedder


def truthful_answer(store: FakeStore, memory_id: str, owner_id: str) -> str:
    """What the real person would say — the memory in their own words.

    Paraphrased (leading word dropped, "I" prefix) rather than echoed verbatim,
    so grading is not passing on an exact-string match.
    """
    for m in store.memories(owner_id):
        if m.id == memory_id:
            words = m.text.rstrip(".").split()
            return "I " + " ".join(words[1:]) if len(words) > 6 else m.text.rstrip(".")
    return ""


CLONE_ANSWERS = [
    "I don't really remember, something about work I think.",
    "It was a pretty normal day, nothing unusual happened.",
    "Yeah I think we talked about the project, the usual stuff.",
    "Honestly it's a bit of a blur, could have been anything.",
    "I'd have to check my notes on that one.",
]
"""What a voice clone sounds like: fluent, confident, and specifically empty."""
