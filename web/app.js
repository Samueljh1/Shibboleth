// Talks only to contracts/api.md. No backend logic here.
const $ = (id) => document.getElementById(id);

const QUESTION_BUDGET = 5; // display only: "Question 2 of 5"

let sessionId = null;
let startBits = null;
let lastQuestionAudio = null;
let startAudio = null; // base64 from the "hold to speak" button
let names = {}; // user_id -> display name, from /enrolled
let busy = false;

// --- transport ------------------------------------------------------------
let bannerTimer = null;
function banner(msg, kind = "err") {
  const el = $("banner");
  el.textContent = msg;
  el.className = kind;
  el.hidden = false;
  clearTimeout(bannerTimer);
  bannerTimer = setTimeout(() => (el.hidden = true), 9000);
}
function clearBanner() {
  $("banner").hidden = true;
}

async function api(path, opts) {
  let r;
  try {
    r = await fetch(path, opts);
  } catch (e) {
    banner(`network error calling ${path} — is uvicorn running?`);
    throw e;
  }
  const txt = await r.text();
  let data = null;
  try {
    data = txt ? JSON.parse(txt) : null;
  } catch {
    data = { detail: txt.slice(0, 300) };
  }
  if (!r.ok) {
    let d = data && (data.detail ?? data.message);
    if (d && typeof d !== "string") d = JSON.stringify(d);
    if (r.status === 503) {
      banner(`503 ${path} — subsystem not wired yet: ${d || "unavailable"}`, "warn");
    } else {
      banner(`${r.status} ${path} — ${d || r.statusText}`);
    }
    const err = new Error(d || r.statusText);
    err.status = r.status;
    throw err;
  }
  return data;
}

const post = (path, body) =>
  api(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });

const b64 = (blob) =>
  new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onerror = rej;
    fr.onload = () => res(String(fr.result).split(",")[1]);
    fr.readAsDataURL(blob);
  });

// --- mic (hold to record) -------------------------------------------------
function pickMime() {
  const opts = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"];
  for (const m of opts) {
    if (window.MediaRecorder && MediaRecorder.isTypeSupported(m)) return m;
  }
  return "";
}

function wireRecorder(btn, timeEl, onDone) {
  let rec = null,
    stream = null,
    chunks = [],
    held = false,
    starting = false,
    tick = null,
    t0 = 0;

  const paint = () => {
    timeEl.textContent = ((Date.now() - t0) / 1000).toFixed(1) + "s";
  };

  const stop = () => {
    held = false;
    btn.classList.remove("live");
    clearInterval(tick);
    if (rec && rec.state === "recording") rec.stop();
  };

  const start = async () => {
    if (held || starting) return;
    held = true;
    starting = true;
    btn.classList.add("live");
    t0 = Date.now();
    timeEl.textContent = "0.0s";
    tick = setInterval(paint, 100);
    try {
      if (!navigator.mediaDevices || !window.MediaRecorder) throw new Error("unsupported");
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      starting = held = false;
      clearInterval(tick);
      btn.classList.remove("live");
      btn.classList.add("broken");
      timeEl.textContent = "mic off";
      banner("microphone unavailable — use the typed answer box, it always works", "warn");
      return;
    }
    starting = false;
    const mime = pickMime();
    rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    chunks = [];
    rec.ondataavailable = (e) => e.data && e.data.size && chunks.push(e.data);
    rec.onstop = async () => {
      clearInterval(tick);
      stream.getTracks().forEach((t) => t.stop());
      const secs = (Date.now() - t0) / 1000;
      timeEl.textContent = secs.toFixed(1) + "s";
      if (!chunks.length) return;
      const audio = await b64(new Blob(chunks, { type: mime || "audio/webm" }));
      onDone(audio, secs);
    };
    rec.start();
    if (!held) stop(); // released before the mic opened
  };

  btn.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    try {
      btn.setPointerCapture(e.pointerId);
    } catch {}
    start();
  });
  btn.addEventListener("pointerup", stop);
  btn.addEventListener("pointercancel", stop);
  btn.addEventListener("lostpointercapture", stop);
  btn.addEventListener("contextmenu", (e) => e.preventDefault());
}

wireRecorder($("rec"), $("rec-time"), (audio, secs) => {
  startAudio = audio;
  $("rec-state").textContent = `audio captured (${secs.toFixed(1)}s) — ready`;
  $("rec-state").classList.add("ready");
});

wireRecorder($("rec-ans"), $("rec-ans-time"), (audio) => {
  submitAnswer({ audio_b64: audio }); // voice answers auto-submit on release
});

// --- TTS ------------------------------------------------------------------
let speakerOn = true;
let player = null;
$("spk").onclick = () => {
  speakerOn = !speakerOn;
  $("spk").classList.toggle("on", speakerOn);
  $("spk").textContent = speakerOn ? "SPEAKER ON" : "SPEAKER OFF";
  if (!speakerOn && player) player.pause();
};
$("replay").onclick = () => play(lastQuestionAudio, true);

function play(audio, force) {
  if (audio) lastQuestionAudio = audio;
  $("replay").disabled = !lastQuestionAudio;
  if (!lastQuestionAudio) return; // no TTS wired — text only, silently
  if (!speakerOn && !force) return;
  try {
    if (player) player.pause();
    player = new Audio("data:audio/mpeg;base64," + lastQuestionAudio);
    player.play().catch(() => {});
  } catch {}
}

// --- flow -----------------------------------------------------------------
$("go").onclick = async () => {
  if (busy) return;
  if (!startAudio) {
    banner("hold HOLD TO SPEAK and say a sentence first", "warn");
    return;
  }
  resetRun();
  busy = true;
  $("go").disabled = true;
  try {
    const d = await post("/session/start", {
      audio_b64: startAudio,
      claimed_id: $("claimed").value.trim() || null,
    });
    sessionId = d.session._id || d.session.id;
    clearBanner();
    render(d.session, d.first_question, null);
    play(d.question_audio_b64);
    $("answer").focus();
  } catch {
    /* banner already shown */
  } finally {
    busy = false;
    $("go").disabled = false;
  }
};

async function submitAnswer(payload) {
  if (!sessionId || busy) return;
  busy = true;
  try {
    const d = await post("/session/answer", { session_id: sessionId, ...payload });
    $("answer").value = "";
    render(d.session, d.next_question, d.result);
    play(d.question_audio_b64);
    if (d.next_question) $("answer").focus();
  } catch {
    /* banner already shown */
  } finally {
    busy = false;
  }
}

$("send").onclick = () => {
  const typed = $("answer").value.trim();
  if (typed) submitAnswer({ answer_text: typed });
};
$("answer").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    $("send").click();
  }
});

$("wipe").onclick = async () => {
  const id = $("wipe-id").value.trim();
  if (!id) return;
  try {
    const d = await post("/session/wipe", { user_id: id });
    banner(`WIPED ${d.deleted} memories for ${nameOf(id)} — they can no longer authenticate`, "ok");
    loadEnrolled();
  } catch {}
};

function resetRun() {
  sessionId = null;
  startBits = null;
  lastQuestionAudio = null;
  $("replay").disabled = true;
  $("log").innerHTML = "";
  $("bars").innerHTML = "";
  $("trace").innerHTML = "";
  $("verdict").textContent = "";
  $("verdict").className = "";
  $("qig").textContent = "-";
  $("candcount").textContent = "";
}

const nameOf = (uid) => names[uid] || uid;

// --- the money visual -----------------------------------------------------
function render(session, question, result) {
  const bits = Number(session.entropy_bits ?? 0);
  if (startBits === null) startBits = Math.max(bits, 0.001);
  $("bits").textContent = bits.toFixed(2);
  $("bits").classList.toggle("zeroed", bits < 0.05);
  const pct = Math.max(0, Math.min(100, (bits / startBits) * 100));
  $("meter-fill").style.width = pct + "%";

  // entropy trace: 3.00 -> 1.58 -> 0.00
  const hist = [startBits].concat(
    (session.asked || []).map((a) => a.entropy_after).filter((v) => v !== null && v !== undefined)
  );
  $("trace").innerHTML = hist
    .map((v, i) => `<b class="${i === hist.length - 1 ? "now" : ""}">${Number(v).toFixed(2)}</b>`)
    .join('<i>&rarr;</i>');

  renderBars(session);

  // question head
  const n = (session.asked || []).length + 1;
  if (question) {
    $("question").textContent = question.question_text;
    $("question").classList.remove("idle");
    $("qcount").textContent = `QUESTION ${Math.min(n, QUESTION_BUDGET)} OF ${QUESTION_BUDGET}`;
    $("qig").textContent = Number(question.ig ?? 0).toFixed(2);
  } else if (!result) {
    $("question").textContent = "no question available — that candidate has no memory left";
    $("question").classList.add("idle");
    $("qcount").textContent = "QUESTION";
    $("qig").textContent = "-";
  }

  $("log").innerHTML = (session.asked || [])
    .map(
      (a, i) => `<li>
        <span class="qn">Q${i + 1}</span>
        <div><b>${esc(a.q)}</b>
        <div class="ans">&ldquo;${esc(a.answer ?? "")}&rdquo;
          <span class="${a.correct ? "ok" : "no"}">${a.correct ? "MATCH" : "NO MATCH"}</span></div>
        <div class="meta">${Number(a.ig ?? 0).toFixed(2)} bits expected &rarr; ${
          a.entropy_after == null ? "?" : Number(a.entropy_after).toFixed(2)
        } bits left</div></div></li>`
    )
    .join("");

  if (result) {
    const who = result.name || nameOf(result.user_id || "");
    $("verdict").className = result.status;
    $("verdict").innerHTML =
      result.status === "identified"
        ? `<div class="vtop">IDENTIFIED</div><div class="vsub">${esc(who)} &middot; ${
            result.questions_used
          } question${result.questions_used === 1 ? "" : "s"}</div>`
        : `<div class="vtop">REJECTED</div><div class="vsub">no candidate cleared the threshold after ${
            result.questions_used ?? (session.asked || []).length
          } questions</div>`;
    $("question").textContent = result.status === "identified" ? "Welcome back." : "Access denied.";
    $("question").classList.add("idle");
    sessionId = null;
  }
}

function renderBars(session) {
  const wrap = $("bars");
  const post_ = session.posterior || {};
  const ranked = Object.entries(post_).sort((a, b) => b[1] - a[1]);
  $("candcount").textContent = ranked.length ? `(${ranked.length})` : "";

  // FLIP: remember where every bar was before we re-sort
  const before = new Map();
  for (const el of wrap.children) before.set(el.dataset.uid, el.getBoundingClientRect().top);

  const live = new Set();
  ranked.forEach(([uid, p], i) => {
    live.add(uid);
    let el = wrap.querySelector(`[data-uid="${cssEsc(uid)}"]`);
    if (!el) {
      el = document.createElement("div");
      el.className = "bar enter";
      el.dataset.uid = uid;
      el.innerHTML =
        '<div class="row"><span class="who"></span><span class="pct"></span></div>' +
        '<div class="track"><div class="fill"></div></div>';
      wrap.appendChild(el);
      requestAnimationFrame(() => el.classList.remove("enter"));
    }
    el.style.order = String(i);
    el.classList.toggle("lead", i === 0);
    el.classList.toggle("dead", p < 0.005);
    const nm = names[uid];
    el.querySelector(".who").innerHTML = nm
      ? `${esc(nm)} <em>${esc(uid)}</em>`
      : `<span>${esc(uid)}</span>`;
    el.querySelector(".pct").textContent = (p * 100).toFixed(1) + "%";
    el.querySelector(".fill").style.width = Math.max(p * 100, 0.4) + "%";
  });

  for (const el of [...wrap.children]) if (!live.has(el.dataset.uid)) el.remove();

  for (const el of wrap.children) {
    const was = before.get(el.dataset.uid);
    if (was === undefined) continue;
    const delta = was - el.getBoundingClientRect().top;
    if (!delta) continue;
    el.style.transition = "none";
    el.style.transform = `translateY(${delta}px)`;
    requestAnimationFrame(() => {
      el.style.transition = "transform .55s cubic-bezier(.2,.7,.2,1)";
      el.style.transform = "";
    });
  }
}

const esc = (s) =>
  String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const cssEsc = (s) => (window.CSS && CSS.escape ? CSS.escape(s) : String(s).replace(/"/g, '\\"'));

// --- who is enrolled ------------------------------------------------------
async function loadEnrolled() {
  let rows = null;
  for (const path of ["/enrolled", "/personas"]) {
    try {
      const r = await fetch(path);
      if (!r.ok) continue;
      const d = await r.json();
      if (Array.isArray(d)) {
        rows = d;
        break;
      }
    } catch {}
  }
  const box = $("enrolled");
  if (!rows) {
    box.textContent = "enrollment list unavailable";
    return;
  }
  names = {};
  rows.forEach((u) => {
    if (u && u.id) names[u.id] = u.name || u.id;
  });
  $("enrolled-n").textContent = `(${rows.length})`;
  box.innerHTML = rows.length
    ? rows
        .map(
          (u) => `<button class="who-chip" data-uid="${esc(u.id)}">
            <b>${esc(u.name || u.id)}</b><span>${esc(u.id)}</span>
            <i class="${(u.memory_count ?? 0) === 0 ? "empty" : ""}">${u.memory_count ?? 0} mem</i>
          </button>`
        )
        .join("")
    : "nobody enrolled yet";
  box.querySelectorAll(".who-chip").forEach((b) => {
    b.onclick = () => {
      $("claimed").value = b.dataset.uid;
      $("wipe-id").value = b.dataset.uid;
    };
  });
}

// --- health ---------------------------------------------------------------
async function loadHealth() {
  try {
    const r = await fetch("/health");
    const d = await r.json();
    const ready = (d && d.ready) || {};
    ["store", "voice", "engine"].forEach((k) => {
      const el = $("h-" + k);
      el.classList.toggle("up", !!ready[k]);
      el.classList.toggle("down", !ready[k]);
      el.textContent = k + (ready[k] ? " up" : " down");
    });
  } catch {
    ["store", "voice", "engine"].forEach((k) => {
      const el = $("h-" + k);
      el.className = "chip down";
      el.textContent = k + " ?";
    });
  }
}

loadHealth();
loadEnrolled();
setInterval(loadHealth, 5000);
