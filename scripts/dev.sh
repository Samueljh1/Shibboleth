#!/usr/bin/env bash
# Shibboleth — one command to run the whole thing.
#   ./scripts/dev.sh
# Binds 0.0.0.0 on purpose: phones on the venue wifi must reach the signup page.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*"; }
err()  { printf '\033[31m%s\033[0m\n' "$*"; }

PY="${PYTHON:-python3}"
PORT="${PORT:-8000}"

# ---------------------------------------------------------------- venv
if [ ! -d .venv ]; then
  bold "==> no .venv — creating one (first run, ~60s)"
  "$PY" -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -m pip install --quiet --upgrade pip
  bold "==> pip install -r requirements.txt"
  python -m pip install -r requirements.txt
else
  # shellcheck disable=SC1091
  source .venv/bin/activate
  # .venv can exist but be half-installed (someone Ctrl-C'd the first run).
  if ! python -c "import fastapi, uvicorn" >/dev/null 2>&1; then
    warn "==> .venv exists but deps are missing — pip install -r requirements.txt"
    python -m pip install -r requirements.txt
  fi
fi

# ---------------------------------------------------------------- .env
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    err "!! .env was MISSING — created one from .env.example. Every key is EMPTY."
    err "   Fill it in (keys are in the hackathon Discord), then re-run this script."
  else
    err "!! .env is MISSING and there is no .env.example to copy."
  fi
fi

# Key names only — values are never read or printed.
missing=()
for key in MONGODB_URI OPENAI_API_KEY ELEVENLABS_API_KEY OPENROUTER_API_KEY; do
  # matches KEY=<something non-empty>, ignoring leading spaces / 'export '
  if ! grep -Eq "^[[:space:]]*(export[[:space:]]+)?${key}[[:space:]]*=[[:space:]]*[^[:space:]]" .env 2>/dev/null; then
    missing+=("$key")
  fi
done

if [ ${#missing[@]} -gt 0 ]; then
  warn "!! .env is missing values for:"
  for k in "${missing[@]}"; do
    case "$k" in
      MONGODB_URI)        warn "   - MONGODB_URI        -> no Atlas: /personas, narrowing and wipe will 503" ;;
      OPENAI_API_KEY)     warn "   - OPENAI_API_KEY     -> no text embeddings: seeding + memory search break" ;;
      ELEVENLABS_API_KEY) warn "   - ELEVENLABS_API_KEY -> no TTS/STT: use the typed-answer path (it always works)" ;;
      OPENROUTER_API_KEY) warn "   - OPENROUTER_API_KEY -> no LLM: question phrasing + grading will 503" ;;
    esac
  done
  warn "   Starting anyway — check http://localhost:${PORT}/health to see what came up."
else
  bold "==> .env looks complete (all 4 keys present)"
fi

# ---------------------------------------------------------------- port
# A second dev.sh on the same port fails deep inside uvicorn. Say it plainly here.
if lsof -ti:"$PORT" >/dev/null 2>&1; then
  err "!! port ${PORT} is already in use (another dev.sh? an old uvicorn?)."
  err "   Free it:  lsof -ti:${PORT} | xargs kill"
  exit 1
fi

# ---------------------------------------------------------------- go
LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || true)"
echo
bold "  stage demo   http://localhost:${PORT}/"
bold "  judge signup http://localhost:${PORT}/signup.html"
bold "  health       http://localhost:${PORT}/health"
[ -n "${LAN_IP:-}" ] && bold "  same wifi    http://${LAN_IP}:${PORT}/signup.html"
bold "  public URL   ./scripts/tunnel.sh   (second terminal)"
echo

exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload
