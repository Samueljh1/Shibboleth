"""Seed Atlas from store/personas/*.json. Sam.

    python -m scripts.seed            # users + memories (+ voiceprints if audio exists)
    python -m scripts.seed --index    # also create the vector search index

Voiceprints are enrolled from store/personas/audio/<user_id>.wav when present
(record a clip, or generate one per persona with a distinct ElevenLabs voice).
Without audio the persona still loads — it just can't be narrowed to yet.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from store.embeddings import VoyageEmbedder

ROOT = Path(__file__).resolve().parent.parent
PERSONAS = ROOT / "store" / "personas"
AUDIO = PERSONAS / "audio"


def _ts(raw: str) -> datetime:
    d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def main(create_index: bool = False) -> None:
    from pymongo import MongoClient

    embedder = VoyageEmbedder(settings)
    db = MongoClient(settings.mongodb_uri)[settings.atlas_db]

    encoder = None
    if AUDIO.exists():
        try:
            from voice.encoder import ResemblyzerEncoder

            encoder = ResemblyzerEncoder()
        except NotImplementedError:
            print("! voice/encoder.py not ready — skipping voiceprint enrollment")

    for path in sorted(PERSONAS.glob("*.json")):
        doc = json.loads(path.read_text())
        uid = doc["id"]

        db.users.replace_one(
            {"_id": uid},
            {"_id": uid, "name": doc["name"], "profile": doc.get("profile", {}),
             "created_at": datetime.now(timezone.utc)},
            upsert=True,
        )

        mems = doc.get("memories", [])
        vecs = embedder.embed_batch([m["text"] for m in mems]) if mems else []
        db.memory_events.delete_many({"user_id": uid})
        if mems:
            db.memory_events.insert_many([
                {
                    "_id": m.get("id", f"m_{uid}_{i:02d}"),
                    "user_id": uid,
                    "ts": _ts(m["ts"]),
                    "kind": m.get("kind", "conversation"),
                    "text": m["text"],
                    "salient_attrs": m.get("salient_attrs", {}),
                    "embedding": vecs[i],
                }
                for i, m in enumerate(mems)
            ])

        wav = AUDIO / f"{uid}.wav"
        if encoder and wav.exists():
            db.voiceprints.replace_one(
                {"_id": f"vp_{uid}"},
                {"_id": f"vp_{uid}", "user_id": uid,
                 "embedding": encoder.embed_voice(wav.read_bytes()),
                 "enrolled_at": datetime.now(timezone.utc)},
                upsert=True,
            )
            print(f"  {uid}: {len(mems)} memories + voiceprint")
        else:
            print(f"  {uid}: {len(mems)} memories (no voiceprint)")

    if create_index:
        from pymongo.operations import SearchIndexModel

        # The index can't be built on a namespace that doesn't exist yet, and
        # voiceprints only appear once someone enrolls with audio. Create it
        # empty so the index is already warm before the demo.
        if "voiceprints" not in db.list_collection_names():
            db.create_collection("voiceprints")

        try:
            db.voiceprints.create_search_index(
                SearchIndexModel(
                    definition={
                        "fields": [{
                            "type": "vector", "path": "embedding",
                            "numDimensions": 256, "similarity": "cosine",
                        }]
                    },
                    name=settings.voice_index,
                    type="vectorSearch",
                )
            )
            print(f"created index {settings.voice_index} (takes ~1 min to build)")
        except Exception as exc:
            print(f"index: {exc}")

    print("seed done")


if __name__ == "__main__":
    main(create_index="--index" in sys.argv)
