/* Shibboleth signup. Vanilla, no deps. Talks to /prompt.txt, /enroll/preview, /enroll. */
"use strict";

const $ = (id) => document.getElementById(id);

let promptText = "";
let doc = null;        // { name, profile, memories: [...] }  — client-side, uncommitted
let audioB64 = null;

/* ---------------------------------------------------------------- banner */

let bannerTimer = null;
function banner(msg, kind) {
  const b = $("banner");
  b.textContent = msg;
  b.className = kind || "";
  b.hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
  clearTimeout(bannerTimer);
  if (kind === "ok") bannerTimer = setTimeout(() => { b.hidden = true; }, 2600);
}
function clearBanner() { clearTimeout(bannerTimer); $("banner").hidden = true; }

/* Never fail silently: every server error surfaces with its own message. */
async function api(path, body) {
  let r;
  try {
    r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (e) {
    throw new Error("Can't reach the server (" + (e.message || e) + ")");
  }
  let data = null;
  try { data = await r.json(); } catch (e) { /* non-JSON error page */ }
  if (!r.ok) {
    let d = data && data.detail;
    if (Array.isArray(d)) d = d.map((x) => x.msg || JSON.stringify(x)).join("; ");
    else if (d && typeof d === "object") d = JSON.stringify(d);
    throw new Error(d || (r.status + " " + r.statusText));
  }
  return data || {};
}

/* ------------------------------------------------------------ 1  prompt */

fetch("/prompt.txt")
  .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.text(); })
  .then((t) => { promptText = t; $("prompt").textContent = t; })
  .catch((e) => {
    $("prompt").textContent = "Could not load the prompt: " + e.message;
    banner("Could not load /prompt.txt — " + e.message);
  });

$("copy").addEventListener("click", async () => {
  if (!promptText) { banner("The prompt hasn't loaded yet."); return; }
  let ok = false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(promptText);
      ok = true;
    }
  } catch (e) { ok = false; }
  if (!ok) ok = legacyCopy(promptText);      // older mobile Safari / http origins
  if (ok) {
    const btn = $("copy");
    btn.textContent = "COPIED ✓";
    setTimeout(() => { btn.textContent = "COPY PROMPT"; }, 2000);
    banner("Copied. Paste it into ChatGPT, Claude or Gemini.", "ok");
  } else {
    banner("Copy blocked by the browser — select the prompt text above and copy it by hand.", "warn");
  }
});

function legacyCopy(text) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.cssText = "position:fixed;top:0;left:0;opacity:0;";
  document.body.appendChild(ta);
  let ok = false;
  try {
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, text.length);   // iOS needs the explicit range
    ok = document.execCommand("copy");
  } catch (e) { ok = false; }
  document.body.removeChild(ta);
  return ok;
}

/* ------------------------------------------------------------ 2  review */

$("review").addEventListener("click", async () => {
  const raw = $("raw").value.trim();
  if (!raw) { banner("Paste your assistant's reply first."); return; }
  const btn = $("review");
  btn.disabled = true;
  btn.textContent = "READING…";
  clearBanner();
  try {
    const out = await api("/enroll/preview", { raw });
    doc = out.doc || { name: "", profile: {}, memories: [] };
    doc.memories = Array.isArray(doc.memories) ? doc.memories : [];
    doc.profile = doc.profile && typeof doc.profile === "object" ? doc.profile : {};
    showWarnings(out.warnings);
    fillDoc();
    unlock("s3");
    unlock("s4");
    $("s3").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    banner(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "REVIEW";
  }
});

function showWarnings(list) {
  const box = $("warnings");
  list = (list || []).filter(Boolean);
  if (!list.length) { box.hidden = true; box.innerHTML = ""; return; }
  const ul = document.createElement("ul");
  list.forEach((w) => {
    const li = document.createElement("li");
    li.textContent = w;
    ul.appendChild(li);
  });
  box.innerHTML = "";
  const h = document.createElement("b");
  h.textContent = "WE CHANGED SOME THINGS";
  box.appendChild(h);
  box.appendChild(ul);
  box.hidden = false;
}

function unlock(id) { $(id).classList.remove("locked"); }

/* ------------------------------------------------------- 3  review + edit */

function fillDoc() {
  $("f-name").value = doc.name || "";
  $("f-role").value = doc.profile.role || "";
  $("f-city").value = doc.profile.city || "";
  renderMems();
}

function fmtDate(ts) {
  if (!ts) return "no date";
  const d = new Date(ts);
  if (isNaN(d)) return String(ts).slice(0, 16);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
         " " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function grow(ta) { ta.style.height = "auto"; ta.style.height = (ta.scrollHeight + 2) + "px"; }

function renderMems() {
  const ul = $("mems");
  ul.innerHTML = "";
  doc.memories.forEach((m, i) => {
    const li = document.createElement("li");
    li.className = "mem";

    const when = document.createElement("div");
    when.className = "when";
    when.textContent = fmtDate(m.ts);
    if (m.kind && m.kind !== "conversation") {
      const em = document.createElement("em");
      em.textContent = m.kind;
      when.appendChild(em);
    }

    const ta = document.createElement("textarea");
    ta.value = m.text || "";
    ta.rows = 2;
    ta.spellcheck = false;
    ta.addEventListener("input", () => { doc.memories[i].text = ta.value; grow(ta); });

    const del = document.createElement("button");
    del.className = "del";
    del.type = "button";
    del.setAttribute("aria-label", "delete this memory");
    del.textContent = "×";
    del.addEventListener("click", () => {
      li.classList.add("going");
      setTimeout(() => { doc.memories.splice(i, 1); renderMems(); }, 140);
    });

    li.appendChild(when);
    li.appendChild(ta);
    li.appendChild(del);
    ul.appendChild(li);
    grow(ta);
  });
  const n = doc.memories.length;
  $("count").textContent = n + (n === 1 ? " memory" : " memories");
  $("empty").hidden = n > 0;
}

$("clearall").addEventListener("click", () => {
  if (!doc || !doc.memories.length) return;
  doc.memories = [];
  renderMems();
  banner("All memories removed. Nothing was ever sent.", "ok");
});

/* --------------------------------------------------------- 4  voice + go */

let media = null, chunks = [], stream = null, t0 = 0, tick = null, recording = false;

function pickMime() {
  const opts = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"];
  if (!window.MediaRecorder) return "";
  for (const m of opts) { if (MediaRecorder.isTypeSupported(m)) return m; }
  return "";
}

function blobToB64(blob) {
  return new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res(String(fr.result).split(",")[1] || "");
    fr.onerror = () => rej(new Error("could not read the recording"));
    fr.readAsDataURL(blob);
  });
}

function recState(msg, cls) {
  const s = $("recstate");
  s.textContent = msg;
  s.className = "recstate" + (cls ? " " + cls : "");
}

async function startRec() {
  if (recording) return;
  clearBanner();
  try {
    if (!navigator.mediaDevices || !window.MediaRecorder) throw new Error("this browser can't record");
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mime = pickMime();
    media = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    chunks = [];
    media.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    media.onstop = async () => {
      stopTimer();
      try { stream.getTracks().forEach((t) => t.stop()); } catch (e) {}
      const secs = (Date.now() - t0) / 1000;
      try {
        const blob = new Blob(chunks, { type: mime || "audio/webm" });
        if (!blob.size) throw new Error("empty recording");
        audioB64 = await blobToB64(blob);
        $("rec").classList.add("have");
        $("reclabel").textContent = "RECORDED ✓ — HOLD TO REDO";
        recState("recorded " + secs.toFixed(1) + "s" + (secs < 2 ? " — a bit short, try ~5s" : ""),
                 secs < 2 ? "bad" : "ready");
      } catch (e) {
        audioB64 = null;
        recState("recording failed — you can still enroll without voice", "bad");
      }
    };
    media.start();
    recording = true;
    t0 = Date.now();
    $("rec").classList.add("live");
    $("rec").classList.remove("have", "broken");
    $("reclabel").textContent = "RECORDING… RELEASE TO STOP";
    recState("keep talking", "");
    tick = setInterval(() => {
      const s = (Date.now() - t0) / 1000;
      $("rectime").textContent = s.toFixed(1) + "s";
      if (s >= 12) stopRec();          // hard cap
    }, 100);
  } catch (e) {
    recording = false;
    $("rec").classList.add("broken");
    $("rec").classList.remove("live");
    $("reclabel").textContent = "MIC UNAVAILABLE";
    recState("no mic — enroll without voice, it still works", "bad");
    banner("Microphone blocked (" + (e.message || e) + "). Voice is optional — press ENROLL ME to continue without it.", "warn");
  }
}

function stopTimer() { clearInterval(tick); tick = null; }

function stopRec() {
  if (!recording) return;
  recording = false;
  $("rec").classList.remove("live");
  $("reclabel").textContent = "HOLD TO RECORD";
  stopTimer();
  try { media.stop(); } catch (e) { /* already dead */ }
}

const recBtn = $("rec");
recBtn.addEventListener("pointerdown", (e) => { e.preventDefault(); startRec(); });
recBtn.addEventListener("pointerup", (e) => { e.preventDefault(); stopRec(); });
recBtn.addEventListener("pointercancel", stopRec);
recBtn.addEventListener("pointerleave", stopRec);
recBtn.addEventListener("contextmenu", (e) => e.preventDefault());

/* --------------------------------------------------------------- enroll */

$("enroll").addEventListener("click", async () => {
  if (!doc) { banner("Review your briefing first (step 2)."); return; }
  if (recording) stopRec();
  const btn = $("enroll");

  doc.name = $("f-name").value.trim() || doc.name || "Anonymous";
  doc.profile = doc.profile || {};
  const role = $("f-role").value.trim();
  const city = $("f-city").value.trim();
  if (role) doc.profile.role = role; else delete doc.profile.role;
  if (city) doc.profile.city = city; else delete doc.profile.city;
  doc.memories = doc.memories.filter((m) => (m.text || "").trim());

  btn.disabled = true;
  btn.textContent = "ENROLLING…";
  clearBanner();
  try {
    const out = await api("/enroll", { doc, audio_b64: audioB64, user_id: null });
    done(out);
  } catch (e) {
    banner(e.message);
    btn.disabled = false;
    btn.textContent = "ENROLL ME";
  }
});

function done(out) {
  $("s1").hidden = true;
  $("s2").hidden = true;
  $("s3").hidden = true;
  $("s4").hidden = true;
  $("s5").hidden = false;
  $("uid").textContent = out.user_id || "(no id returned)";
  const bits = [
    (out.memories != null ? out.memories : 0) + " memories stored",
    out.voiceprint ? "voiceprint enrolled" : "no voiceprint — text questions only",
  ];
  $("donemeta").textContent = bits.join(" · ");
  const warns = (out.warnings || []).filter(Boolean);
  if (warns.length) banner(warns.join(" "), "warn");
  window.scrollTo({ top: 0, behavior: "smooth" });
}
