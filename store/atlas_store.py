"""MongoDB Atlas store. Sam.

Collections: users, voiceprints (vector index), memory_events, auth_sessions.
"""

from __future__ import annotations

from pymongo import MongoClient
from pymongo.server_api import ServerApi

from app.config import Settings
from contracts.interfaces import Embedder
from contracts.models import AuthSession, MemoryEvent, User


class AtlasStore:
    """Implements contracts.interfaces.Store."""

    def __init__(self, settings: Settings, embedder: Embedder) -> None:
        if not settings.mongodb_uri:
            raise RuntimeError("MONGODB_URI is not set")
        if "<db_password>" in settings.mongodb_uri:
            raise RuntimeError("MONGO_PASSWORD is not set (URI still has <db_password>)")
        self.s = settings
        self.embedder = embedder
        self.db = MongoClient(settings.mongodb_uri, server_api=ServerApi("1"))[settings.atlas_db]

    def narrow(self, voice_vec: list[float], k: int) -> list[tuple[str, float]]:
        pipeline = [
            {
                "$vectorSearch": {
                    "index": self.s.voice_index,
                    "path": "embedding",
                    "queryVector": list(voice_vec),
                    "numCandidates": 200,
                    "limit": max(k * 3, 10),
                }
            },
            {"$project": {"user_id": 1, "sim": {"$meta": "vectorSearchScore"}}},
        ]
        best: dict[str, float] = {}
        for d in self.db.voiceprints.aggregate(pipeline):
            uid, sim = d["user_id"], float(d["sim"])
            if sim > best.get(uid, -1.0):  # a user may have several voiceprints
                best[uid] = sim
        return sorted(best.items(), key=lambda t: t[1], reverse=True)[:k]

    def memories(self, user_id: str) -> list[MemoryEvent]:
        docs = self.db.memory_events.find({"user_id": user_id}).sort("ts", -1)
        return [MemoryEvent(**d) for d in docs]

    def get_user(self, user_id: str) -> User:
        d = self.db.users.find_one({"_id": user_id})
        if not d:
            raise KeyError(f"unknown user: {user_id}")
        return User(**d)

    def list_users(self) -> list[User]:
        return [User(**d) for d in self.db.users.find()]

    def wipe_user_memory(self, user_id: str) -> None:
        self.db.memory_events.delete_many({"user_id": user_id})

    def save_session(self, session: AuthSession) -> None:
        doc = session.model_dump(by_alias=True)
        self.db.auth_sessions.replace_one({"_id": session.id}, doc, upsert=True)

    def get_session(self, session_id: str) -> AuthSession | None:
        d = self.db.auth_sessions.find_one({"_id": session_id})
        return AuthSession(**d) if d else None
