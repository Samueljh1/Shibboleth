/* Shibboleth signup — vanilla, mobile first.
   Steps: copy prompt -> paste JSON -> POST /enroll/preview -> edit -> POST /enroll. */

const $ = (id) => document.getElementById(id);

let DOC = null;        // the enrollment doc we will POST back
let MEMS = [];         // live array of memory objects (references into DOC)
let MEM_KEY = "memories";
let AUDIO_B64 = null;

const FALLBACK_PROMPT = `You are helping me enroll in Shibboleth, a system that proves who I am by
asking about things only I would remember.

From what you know about me in this conversation, write 15-25 short, concrete,
specific episodic memories — decisions I made, things that happened, details a
stranger or a voice clone could not guess. No passwords, no card numbers, no
government IDs, nothing you would not say out loud.

Reply with ONLY this JSON, no commentary, no code fences:

{
  "name": "<my first name>",
  "memories": [
    { "ts": "2026-05-02", "kind": "decision", "text": "Switched the retriever to hybrid rankFusion after the Tuesday review." }
  ]
}

"kind" is one of: conversation, fact, decision, event.`;

/* ---------- error banner ---------- */
function showError(msg) {
  $("banner-msg").textContent = String(msg);
  $("banner").hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
}
function clearError() { $("banner").hidden = true; }
$("banner-x").addEventListener("click", clearError);

function detailOf(data, fallback) {
  if (data && typeof data === "object") {
    const d = data.detail !== undefined ? data.detail : data.error;
    if (typeof d === "string") return d;
    if (d) return JSON.stringify(d);
    if (typeof data.message === "string") return data.message;
  }
  return fallback;
}

async function api(path, body) {
  let res;
  try {
    res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (e) {
    throw new Error("Could not reach the server (" + e.message + ")");
  }
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { /* not json */ }
  if (!res.ok) {
    throw new Error(detailOf(data, text || (res.status + " " + res.statusText)));
  }
  return data === null ? {} : data;
}

/* ---------- step 1: prompt ---------- */
let PROMPT_TEXT = FALLBACK_PROMPT;

fetch("/prompt.txt", { cache: "no-store" })
  .then((r) => (r.ok ? r.text() : Promise.reject(new Error(r.status))))
  .then((t) => { if (t && t.trim()) { PROMPT_TEXT = t.trim(); } })
  .catch(() => { /* server has no prompt.txt yet — use the built-in one */ })
  .finally(() => { $("prompt").textContent = PROMPT_TEXT; });

function legacyCopy(text) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.top = "0";
  ta.style.left = "0";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  let ok = false;
  try {
    ta.focus();
    ta.select();
    if (ta.setSelectionRange) ta.setSelectionRange(0, text.length); // iOS Safari
    ok = document.execCommand("copy");
  } catch (e) { ok = false; }
  document.body.removeChild(ta);
  return ok;
}

$("copy").addEventListener("click", async () => {
  const btn = $("copy");
  let ok = false;
  if (navigator.clipboard && window.isSecureContext) {
    try { await navigator.clipboard.writeText(PROMPT_TEXT); ok = true; } catch (e) { ok = false; }
  }
  if (!ok) ok = legacyCopy(PROMPT_TEXT);
  if (ok) {
    btn.textContent = "Copied";
    btn.classList.add("ok");
    btn.classList.remove("primary");
    setTimeout(() => {
      btn.textContent = "Copy prompt";
      btn.classList.remove("ok");
      btn.classList.add("primary");
    }, 2200);
  } else {
    showError("Couldn't copy automatically — select the prompt text above and copy it by hand.");
  }
});

/* ---------- step 2: preview ---------- */
function pickDoc(data) {
  if (!data || typeof data !== "object") return null;
  const d = data.doc || data.parsed || data.document || data.enrollment || data.user;
  if (d && typeof d === "object") return d;
  return data;
}

function pickMemories(doc) {
  const keys = ["memories", "memory_events", "events", "items"];
  for (const k of keys) {
    if (Array.isArray(doc[k])) { MEM_KEY = k; return doc[k]; }
  }
  MEM_KEY = "memories";
  return [];
}

$("review").addEventListener("click", async () => {
  clearError();
  const raw = $("raw").value.trim();
  if (!raw) { showError("Paste the assistant's reply first."); return; }
  const btn = $("review");
  btn.disabled = true; btn.classList.add("busy"); btn.textContent = "Reviewing…";
  try {
    const data = await api("/enroll/preview", { raw: raw });
    DOC = pickDoc(data) || {};
    MEMS = pickMemories(DOC);
    renderWarnings(data.warnings || (DOC && DOC.warnings) || []);
    if (!MEMS.length) {
      showError("No memories were parsed out of that reply. Check the assistant returned the JSON block.");
    }
    setupNameField();
    renderMemories();
    unlock();
  } catch (e) {
    showError(e.message);
  } finally {
    btn.disabled = false; btn.classList.remove("busy"); btn.textContent = "Review";
  }
});

function renderWarnings(list) {
  const box = $("warnings");
  box.innerHTML = "";
  const arr = Array.isArray(list) ? list : (list ? [list] : []);
  if (!arr.length) { box.hidden = true; return; }
  const h = document.createElement("b");
  h.textContent = "WARNINGS";
  box.appendChild(h);
  arr.forEach((w) => {
    const d = document.createElement("div");
    d.textContent = "• " + (typeof w === "string" ? w : JSON.stringify(w));
    box.appendChild(d);
  });
  box.hidden = false;
}

function unlock() {
  $("step3").classList.remove("locked");
  $("step4").classList.remove("locked");
  $("step3").scrollIntoView({ behavior: "smooth", block: "start" });
}

function setupNameField() {
  const nameKeys = ["name", "user_name", "display_name"];
  let val = "";
  for (const k of nameKeys) {
    if (typeof DOC[k] === "string" && DOC[k]) { val = DOC[k]; break; }
  }
  $("name-field").hidden = false;
  $("name").value = val;
}

/* ---------- step 3: edit ---------- */
function memDate(m) {
  const v = m.ts || m.date || m.when || m.timestamp || "";
  if (!v) return "no date";
  const d = new Date(v);
  if (isNaN(d.getTime())) return String(v);
  return d.toISOString().slice(0, 10);
}
function memText(m) {
  return m.text || m.memory || m.content || "";
}

function autoGrow(ta) {
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight + 2, 400) + "px";
}

function renderMemories() {
  const box = $("memories");
  box.innerHTML = "";
  MEMS.forEach((m, i) => {
    const row = document.createElement("div");
    row.className = "mem";

    const col = document.createElement("div");
    col.className = "col";

    const date = document.createElement("div");
    date.className = "date";
    date.textContent = memDate(m);

    const ta = document.createElement("textarea");
    ta.value = memText(m);
    ta.rows = 2;
    ta.setAttribute("aria-label", "memory " + (i + 1));
    ta.addEventListener("input", () => {
      m.text = ta.value;
      if ("memory" in m) delete m.memory;
      if ("content" in m) delete m.content;
      autoGrow(ta);
    });

    col.appendChild(date);
    col.appendChild(ta);

    const del = document.createElement("button");
    del.className = "del";
    del.type = "button";
    del.textContent = "×";
    del.setAttribute("aria-label", "delete this memory");
    del.addEventListener("click", () => {
      const idx = MEMS.indexOf(m);
      if (idx >= 0) MEMS.splice(idx, 1);
      renderMemories();
    });

    row.appendChild(col);
    row.appendChild(del);
    box.appendChild(row);
    autoGrow(ta);
  });
  $("count").textContent = MEMS.length + (MEMS.length === 1 ? " memory" : " memories");
  $("empty").hidden = MEMS.length > 0;
}

/* ---------- step 4: record ---------- */
const MAX_MS = 8000;
let stream = null, recorder = null, chunks = [], t0 = 0, tick = null, stopping = false;

function setRecState(msg, good) {
  const el = $("rec-state");
  el.textContent = msg;
  el.classList.toggle("good", !!good);
  el.classList.toggle("dim", !good);
}

async function startRec() {
  if (recorder && recorder.state === "recording") return;
  if (!navigator.mediaDevices || !window.MediaRecorder) {
    setRecState("this browser can't record — enroll without voice", false);
    return;
  }
  try {
    if (!stream) stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    setRecState("mic blocked — you can still enroll without voice", false);
    showError("Microphone unavailable (" + (e.name || e.message) + "). Voice is optional — press Enroll me to continue without it.");
    return;
  }
  chunks = [];
  stopping = false;
  try {
    recorder = new MediaRecorder(stream);
  } catch (e) {
    setRecState("recording unsupported — enroll without voice", false);
    return;
  }
  recorder.ondataavailable = (ev) => { if (ev.data && ev.data.size) chunks.push(ev.data); };
  recorder.onstop = onStop;
  recorder.start();
  t0 = Date.now();
  $("rec").classList.add("live");
  $("rec").textContent = "Recording… release to stop";
  setRecState("0.0s", false);
  tick = setInterval(() => {
    const s = (Date.now() - t0) / 1000;
    setRecState(s.toFixed(1) + "s", false);
    if (s * 1000 >= MAX_MS) stopRec();
  }, 100);
}

function stopRec() {
  if (!recorder || recorder.state !== "recording" || stopping) return;
  stopping = true;
  clearInterval(tick);
  try { recorder.stop(); } catch (e) { /* ignore */ }
  $("rec").classList.remove("live");
  $("rec").textContent = "Hold to record";
}

function onStop() {
  const dur = (Date.now() - t0) / 1000;
  const blob = new Blob(chunks, { type: (recorder && recorder.mimeType) || "audio/webm" });
  if (!blob.size || dur < 0.6) {
    AUDIO_B64 = null;
    setRecState("too short — hold for about five seconds", false);
    return;
  }
  const fr = new FileReader();
  fr.onloadend = () => {
    const s = String(fr.result || "");
    const comma = s.indexOf(",");
    AUDIO_B64 = comma >= 0 ? s.slice(comma + 1) : null;
    if (AUDIO_B64) setRecState("recorded — " + dur.toFixed(1) + "s ✓", true);
    else setRecState("couldn't encode the audio — enroll without voice", false);
  };
  fr.onerror = () => { AUDIO_B64 = null; setRecState("couldn't read the audio — enroll without voice", false); };
  fr.readAsDataURL(blob);
}

const recBtn = $("rec");
recBtn.addEventListener("pointerdown", (e) => { e.preventDefault(); startRec(); });
recBtn.addEventListener("pointerup", (e) => { e.preventDefault(); stopRec(); });
recBtn.addEventListener("pointercancel", () => stopRec());
recBtn.addEventListener("pointerleave", () => stopRec());
recBtn.addEventListener("contextmenu", (e) => e.preventDefault());

/* ---------- enroll ---------- */
$("enroll").addEventListener("click", async () => {
  clearError();
  if (!DOC) { showError("Review your memories first (step 2)."); return; }
  const kept = MEMS.filter((m) => (memText(m) || "").trim().length > 0);
  if (!kept.length) { showError("You deleted every memory — there'd be nothing to authenticate against."); return; }

  DOC[MEM_KEY] = kept;
  const nm = $("name").value.trim();
  if (nm) DOC.name = nm;

  const btn = $("enroll");
  btn.disabled = true; btn.classList.add("busy"); btn.textContent = "Enrolling…";
  try {
    const data = await api("/enroll", { doc: DOC, audio_b64: AUDIO_B64 });
    const uid = data.user_id || data.id || data._id || (data.user && (data.user.id || data.user._id));
    $("uid").textContent = uid || "enrolled";
    $("done-note").textContent = AUDIO_B64
      ? "Voiceprint + " + kept.length + " memories stored."
      : kept.length + " memories stored. No voiceprint — you can still be identified by memory.";
    ["step1", "step2", "step3", "step4"].forEach((id) => { $(id).hidden = true; });
    $("done").hidden = false;
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (e) {
    showError(e.message);
  } finally {
    btn.disabled = false; btn.classList.remove("busy"); btn.textContent = "Enroll me";
  }
});
