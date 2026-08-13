# `store/` — Task B · **owner: Sam**

Atlas access + seed personas. Collections: `users`, `voiceprints` (vector index
on `embedding`, 256-d cosine), `memory_events`, `auth_sessions`.

- `atlas_store.py` — `AtlasStore`, implements `contracts.interfaces.Store`
- `embeddings.py` — `OpenAIEmbedder`, implements `Embedder`
- `personas/*.json` — the seed personas
- `personas/audio/<user_id>.wav` — reference clip per persona (enrollment)
- `../scripts/seed.py` — loads it all, `--index` also creates the vector index

## Persona format

    {
      "id": "u_ada",
      "name": "Ada",
      "profile": { "role": "founder", "city": "SF" },
      "memories": [
        { "ts": "2026-08-12T15:40:00Z", "kind": "decision",
          "text": "Switched the retriever to hybrid rankFusion.",
          "salient_attrs": { "current_project": "Shibboleth" } }
      ]
    }

Memory `id` is optional (generated as `m_<user>_<NN>`). Embeddings are computed
at seed time, never stored in the JSON.

**Write them to be discriminating** — the engine can only separate people on
details they don't share. Specific, recent, private, non-scrapeable: decisions,
numbers, small conversational quirks. Spread timestamps across the last few days
so "yesterday afternoon" questions work. 8–10 personas, 15–25 memories each.

The build has to live in the MongoDB hackathon sandbox to stay finalist-eligible.
