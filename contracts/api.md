# HTTP contract

The frontend (`web/`, Sam) depends on **only** this file. The backend
(`app/main.py`, Sam) must satisfy it. Change it in a PR titled `contract:` and
tell the other person.

Base URL: `http://localhost:8000`. All bodies and responses are JSON.

Two pages are served off the same app: `/` is the stage demo, `/signup.html` is
the public enrollment page judges use on their phones.

**Every response that touches a session returns the full `AuthSession`** so the
UI can animate posterior bars and the entropy meter without extra round-trips.

---

## POST /session/start

Begin an auth attempt. Send audio, or in mock/demo mode a speaker hint.

Request:

    {
      "audio_b64": "UklGR...",     // base64 wav, required
      "claimed_id": "u_ada"        // optional: identity being claimed (clone demo)
    }

Response 200:

    {
      "session": { ...AuthSession... },
      "first_question": { ...QuestionSpec... } | null
    }

## POST /session/answer

Submit one answer. Typed answers are first-class — the demo must survive a loud
room.

Request (exactly one of `answer_text` / `audio_b64`):

    { "session_id": "s_...", "answer_text": "hybrid rankFusion" }

Response 200:

    {
      "session": { ...AuthSession, status may now be identified|rejected... },
      "next_question": { ...QuestionSpec... } | null,   // null when finished
      "result": {                                       // null while in_progress
        "status": "identified",
        "user_id": "u_ada",
        "name": "Ada",
        "questions_used": 2
      } | null
    }

## POST /session/wipe

Delete a user's episodic memory live on stage. Afterwards that user can no
longer be authenticated — the proof that MongoDB was doing the work.

Request: `{ "user_id": "u_ada" }` → Response: `{ "ok": true, "deleted": 21 }`

## GET /personas

Enrolled users, for the demo's speaker picker.

Response: `[ { "id": "u_ada", "name": "Ada", "role": "founder", "memory_count": 21 } ]`

## Enrollment (signup site)

How a stranger becomes an enrolled user: they copy a prompt into their own AI
assistant, paste its JSON reply here, review and edit it, then commit.

### GET /prompt.txt

The briefing prompt, `text/plain`. Served from `web/prompt.txt`.

### POST /enroll/preview

Request: `{ "raw": "<whatever the assistant replied>" }`

Response: `{ "doc": {...}, "warnings": ["dropped 2 memories containing digits"], "memory_count": 18 }`

Parses leniently (raw JSON, embedded JSON block, then an LLM conversion), then
sanitises. Nothing is written to the database by this call — it exists so the
user can review and delete before committing. 400 with a readable message when
the paste can't be parsed.

### POST /enroll

Request: `{ "doc": {...edited doc...}, "audio_b64": "..."|null, "user_id": null }`

Response: `{ "user_id": "u_ada_4f1c", "name": "Ada", "memories": 18, "voiceprint": true, "warnings": [] }`

Sanitises again server-side — the client is never trusted. Voice is optional:
without usable audio the user still enrolls, just with `voiceprint: false`, and
can't be narrowed to until a voiceprint exists.

### GET /enrolled

Response: `[ { "id": "u_ada", "name": "Ada", "memory_count": 18 } ]`

## GET /health

Response: `{ "ok": true, "ready": { "store": true, "voice": true, "engine": false } }`

Check this before a demo run. A subsystem that is not wired yet returns 503 from
its endpoints rather than pretending to work.

---

## Object shapes

Authoritative definitions live in [contracts/models.py](models.py); this is the
JSON view of them.

### AuthSession

    {
      "_id": "s_7f3a",
      "candidate_ids": ["u_ada", "u_ben", "u_cara"],
      "posterior": { "u_ada": 0.62, "u_ben": 0.30, "u_cara": 0.08 },
      "entropy_bits": 1.05,
      "asked": [ ...AskedQuestion... ],
      "status": "in_progress" | "identified" | "rejected",
      "claimed_id": "u_ada" | null,
      "created_at": "2026-08-13T22:00:00Z"
    }

`posterior` keys are always a subset of `candidate_ids` and sum to 1.0. The UI
sorts bars by probability descending.

### QuestionSpec

    {
      "memory_id": "m_ada_04",
      "owner_id": "u_ada",
      "target_attr": "current_project" | null,
      "ig": 1.21,                       // expected information gain, bits
      "question_text": "What did you decide about your retriever on Tuesday?"
    }

### AskedQuestion

    {
      "q": "What did you decide...",
      "memory_id": "m_ada_04",
      "owner_id": "u_ada",
      "target_attr": "current_project",
      "ig": 1.21,
      "answer": "switching to hybrid rankFusion",
      "graded": true,
      "correct": true,
      "entropy_after": 0.41
    }

## Errors

Standard FastAPI shape: `{ "detail": "..." }` with 400 for a bad request, 404
for an unknown `session_id` or `user_id`, 409 for answering a finished session.

Typed answers are supported everywhere audio is, and the UI always offers the
typed path — Pier 48 is loud and a failed STT call must not end the demo.
