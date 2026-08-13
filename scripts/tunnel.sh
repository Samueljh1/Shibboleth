#!/usr/bin/env bash
# Shibboleth — one command to be publicly reachable.
#   ./scripts/tunnel.sh          (run ./scripts/dev.sh in another terminal first)
# Public HTTPS -> localhost:8000, so judges can enroll from their phones.
set -uo pipefail

PORT="${PORT:-8000}"
bold() { printf '\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*"; }
err()  { printf '\033[31m%s\033[0m\n' "$*"; }

banner() {
  url="$1"
  echo
  echo "======================================================================"
  bold "  PUBLIC URL     $url"
  bold "  JUDGE SIGNUP   ${url}/signup.html   <-- put THIS on the projector"
  bold "  STAGE DEMO     ${url}/"
  echo "======================================================================"
  echo
  # Scannable straight off the projector. Full-screen the terminal, big font.
  if command -v qrencode >/dev/null 2>&1; then
    qrencode -t ANSI "${url}/signup.html" || true
  else
    bold "  QR for the projector:  brew install qrencode"
    bold "                         qrencode -t ANSI '${url}/signup.html'"
    bold "  (or paste the signup URL into any phone QR site and share the image)"
  fi
  echo
  bold "  Sanity check:  curl -s ${url}/health"
  echo
}

# Is the app actually up? Not fatal — the tunnel can start first.
if ! curl -fsS --max-time 2 "http://localhost:${PORT}/health" >/dev/null 2>&1; then
  warn "!! nothing answering on localhost:${PORT} yet — start ./scripts/dev.sh in another terminal."
  warn "   Tunnelling anyway; it will connect as soon as the app is up."
fi

# ------------------------------------------------------------ cloudflared
if command -v cloudflared >/dev/null 2>&1; then
  bold "==> cloudflared tunnel -> http://localhost:${PORT}  (no account needed)"
  LOG="$(mktemp /tmp/shibboleth-tunnel.XXXXXX)"
  cloudflared tunnel --url "http://localhost:${PORT}" >"$LOG" 2>&1 &
  TUN_PID=$!
  TAIL_PID=""
  trap 'kill "$TUN_PID" ${TAIL_PID:-} 2>/dev/null; exit 0' INT TERM

  URL=""
  for _ in $(seq 1 40); do   # up to ~20s
    URL="$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" 2>/dev/null | head -1)"
    [ -n "$URL" ] && break
    kill -0 "$TUN_PID" 2>/dev/null || break
    sleep 0.5
  done

  if [ -n "$URL" ]; then
    banner "$URL"
    bold "  (Ctrl-C to stop. Live log: $LOG)"
  else
    err "!! cloudflared did not print a URL. Log follows:"
    cat "$LOG"
  fi
  tail -f "$LOG" &
  TAIL_PID=$!
  wait "$TUN_PID"
  kill "$TAIL_PID" 2>/dev/null
  exit 0
fi

# ------------------------------------------------------------ ngrok
if command -v ngrok >/dev/null 2>&1; then
  warn "==> cloudflared not found; falling back to ngrok"
  if ! ngrok config check >/dev/null 2>&1; then
    err "!! ngrok has no valid config. Run once:  ngrok config add-authtoken <token>"
    err "   (free token at https://dashboard.ngrok.com) — or: brew install cloudflared"
    exit 1
  fi
  LOG="$(mktemp /tmp/shibboleth-ngrok.XXXXXX)"
  ngrok http "$PORT" --log stdout >"$LOG" 2>&1 &
  TUN_PID=$!
  trap 'kill "$TUN_PID" 2>/dev/null; exit 0' INT TERM

  URL=""
  for _ in $(seq 1 30); do
    URL="$(curl -fsS --max-time 1 http://127.0.0.1:4040/api/tunnels 2>/dev/null \
      | grep -Eo 'https://[a-zA-Z0-9.-]+\.ngrok[a-z.-]*\.(io|app|dev)' | head -1)"
    [ -n "$URL" ] && break
    kill -0 "$TUN_PID" 2>/dev/null || break
    sleep 0.5
  done

  if [ -n "$URL" ]; then
    banner "$URL"
    bold "  (Ctrl-C to stop. Log: $LOG — dashboard: http://127.0.0.1:4040)"
    warn "  ngrok free shows an interstitial 'Visit Site' page on first load —"
    warn "  tell the judges to tap through it. cloudflared has no interstitial."
  else
    err "!! could not read the ngrok URL — open http://127.0.0.1:4040 to see it."
    cat "$LOG"
  fi
  wait "$TUN_PID"
  exit 0
fi

# ------------------------------------------------------------ neither
err "!! No tunnel tool installed. Install one (cloudflared is the fast path):"
echo
bold "    brew install cloudflared"
bold "    brew install ngrok"
echo
err "   cloudflared needs no account. ngrok needs 'ngrok config add-authtoken <token>'."
err "   Fallback with zero installs: judges on the same wifi can use your LAN IP —"
err "   see DEPLOY.md ('If the tunnel dies')."
exit 1
