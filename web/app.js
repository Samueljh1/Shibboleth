// Talks only to contracts/api.md. No backend logic here.
const $ = (id) => document.getElementById(id);
let sessionId = null;
let startBits = null;
let recorder = null;
let chunks = [];
let lastAudio = null; // base64 wav/webm from the most recent recording

const post = async (path, body) => {
  const r = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(JSON.stringify(data.detail || data));
  return data;
};

const b64 = (blob) =>
  new Promise((res) => {
    const fr = new FileReader();
    fr.onload = () => res(fr.result.split(",")[1]);
    fr.readAsDataURL(blob);
  });

// --- mic ------------------------------------------------------------------
$("rec").onmousedown = async () => {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  recorder = new MediaRecorder(stream);
  chunks = [];
  recorder.ondataavailable = (e) => chunks.push(e.data);
  recorder.onstop = async () => {
    lastAudio = await b64(new Blob(chunks, { type: "audio/webm" }));
    stream.getTracks().forEach((t) => t.stop());
  };
  recorder.start();
  $("rec").classList.add("live");
};
$("rec").onmouseup = () => {
  recorder && recorder.stop();
  $("rec").classList.remove("live");
};

// --- flow -----------------------------------------------------------------
$("go").onclick = async () => {
  if (!lastAudio) return alert("Hold the button and say a sentence first.");
  reset();
  const claimed = $("claimed").value.trim() || null;
  const d = await post("/session/start", { audio_b64: lastAudio, claimed_id: claimed });
  sessionId = d.session._id;
  render(d.session, d.first_question, null);
  play(d.question_audio_b64);
};

$("send").onclick = async () => {
  if (!sessionId) return;
  const typed = $("answer").value.trim();
  const body = { session_id: sessionId };
  if (typed) body.answer_text = typed;
  else if (lastAudio) body.audio_b64 = lastAudio;
  else return;

  const d = await post("/session/answer", body);
  $("answer").value = "";
  lastAudio = null;
  render(d.session, d.next_question, d.result);
  play(d.question_audio_b64);
};

$("wipe").onclick = async () => {
  const id = $("wipe-id").value.trim();
  if (!id) return;
  const d = await post("/session/wipe", { user_id: id });
  alert(`wiped ${d.deleted} memories for ${id}`);
};

const play = (audio) => {
  if (audio) new Audio("data:audio/mpeg;base64," + audio).play().catch(() => {});
};

function reset() {
  startBits = null;
  $("log").innerHTML = "";
  $("verdict").textContent = "";
  $("verdict").className = "";
}

// --- the money visual -----------------------------------------------------
function render(session, question, result) {
  const bits = session.entropy_bits;
  if (startBits === null) startBits = Math.max(bits, 0.001);
  $("bits").textContent = bits.toFixed(2);
  $("meter-fill").style.width = `${Math.max(0, Math.min(100, (bits / startBits) * 100))}%`;

  const ranked = Object.entries(session.posterior).sort((a, b) => b[1] - a[1]);
  $("bars").innerHTML = ranked
    .map(
      ([uid, p], i) => `
      <div class="bar ${i === 0 ? "lead" : ""}">
        <div class="row"><span>${uid}</span><span>${(p * 100).toFixed(1)}%</span></div>
        <div class="track"><div class="fill" style="width:${p * 100}%"></div></div>
      </div>`
    )
    .join("");

  $("log").innerHTML = session.asked
    .map(
      (a) => `<li><b>Q:</b> ${a.q}<br><b>A:</b> ${a.answer ?? ""}
              <span class="${a.correct ? "ok" : "no"}">${a.correct ? "match" : "no match"}</span>
              &middot; ${a.ig?.toFixed(2) ?? "?"} bits expected
              &rarr; ${a.entropy_after?.toFixed(2) ?? "?"} bits left</li>`
    )
    .join("");

  $("question").textContent = question ? question.question_text : "-";

  if (result) {
    $("verdict").className = result.status;
    $("verdict").textContent =
      result.status === "identified"
        ? `IDENTIFIED: ${result.name} in ${result.questions_used}Q`
        : `REJECTED after ${result.questions_used}Q`;
    sessionId = null;
  }
}
