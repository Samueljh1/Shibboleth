# DEPLOY — the 60-second runbook

Shibboleth runs on **the presenter's laptop**. It cannot go serverless: the voice
encoder is resemblyzer/torch. The laptop serves the demo; a tunnel exposes the
signup page to the venue so judges can enroll from their phones.

## Two terminals. That's the whole thing.

```bash
# terminal 1 — the app (creates .venv + installs on first run)
./scripts/dev.sh

# terminal 2 — public HTTPS URL for the room
./scripts/tunnel.sh
```

Before the first run:

```bash
cp .env.example .env      # fill: MONGODB_URI, OPENAI_API_KEY, ELEVENLABS_API_KEY, OPENROUTER_API_KEY
./scripts/dev.sh          # creates .venv, pip installs, then serves
# once, in another terminal (venv active) — seeds Atlas + builds the vector index:
source .venv/bin/activate && python -m scripts.seed --index
```

`dev.sh` names any missing key (never prints values) and starts anyway, so a
missing ElevenLabs key costs you TTS, not the demo. It also creates `.venv` and
installs on first run, repairs a half-installed `.venv`, and copies
`.env.example` to `.env` if you forgot. The one thing it refuses to do is start
on a busy port — it tells you the `kill` line instead.

## The two URLs

| | URL | Who |
| --- | --- | --- |
| Stage demo | `http://localhost:8000/` | you, on the projector |
| Judge signup | `<public-url>/signup.html` | judges, on their phones |

`tunnel.sh` prints both in a big banner. The signup one is what goes on screen.

It prefers **cloudflared** (no account) and falls back to **ngrok**. On the
presenter's laptop right now: cloudflared is *not* installed, ngrok *is* and is
authed — so it takes the ngrok path and works. Caveat on that path: ngrok's free
tier shows a "Visit Site" interstitial on first load, so tell judges to tap
through it. To lose the interstitial, spend 20 seconds on
`brew install cloudflared` before you go on.

## Check it's alive

```bash
curl -s localhost:8000/health
# {"ok":true,"ready":{"store":true,"voice":true,"engine":true}}
```

Any `false` = that subsystem didn't construct; its endpoints return 503 and the
rest still works. Check this **before** you walk on stage, and again after the
tunnel comes up (`curl -s <public-url>/health`).

## QR code for the projector

`tunnel.sh` prints the signup QR into its own banner automatically — but only if
`qrencode` is installed, and right now it isn't:

```bash
brew install qrencode      # do this before you go on stage
```

Then the QR appears in the banner. Manually, for any URL:

```bash
qrencode -t ANSI "https://your-tunnel.trycloudflare.com/signup.html"
```

Full-screen the terminal, big font, judges scan it off the projector. No
qrencode and no time? Paste the signup URL into any phone QR site (e.g. qr.io)
and screen-share the image.

## If the tunnel dies mid-demo

Don't debug it on stage. Fall back to the LAN — the laptop is already bound to
`0.0.0.0`, so anyone on the venue wifi can reach it directly by IP:

```bash
ipconfig getifaddr en0        # e.g. 192.168.1.42
```

Then the signup link is `http://192.168.1.42:8000/signup.html` and the demo is
`http://192.168.1.42:8000/`. Same page, no HTTPS. **Caveat:** browsers block
microphone access on plain `http://` for non-localhost origins, so LAN judges
can still enroll/sign up and use the typed-answer path, but phone mic capture
needs the HTTPS tunnel. Typed answers are first-class everywhere — Pier 48 is
loud and that path is the one that always works.

Meanwhile, in a spare terminal: `./scripts/tunnel.sh` again gives a fresh URL
(cloudflared quick tunnels get a new hostname each time — re-generate the QR).

Guest wifi with client isolation blocks even LAN access. If that's the venue,
the fallback is a phone hotspot: put the laptop and the judges' phones on it,
then use the laptop's hotspot IP.

## Gotchas

- Rerunning `scripts/seed.py --index` is safe; the Atlas vector index takes a
  minute to build before `narrow` returns anything.
- `--reload` is on, so edits restart the server. Stop editing during the demo.
- Port 8000 taken? `lsof -ti:8000 | xargs kill`. Both scripts honour `PORT=…`,
  but leave it at 8000 on stage — one less variable, and every URL above assumes
  it.
- `voice/` and `engine/` may still be stubs. `/health` is the truth; the typed
  answer path and `/signup.html` do not depend on them.
