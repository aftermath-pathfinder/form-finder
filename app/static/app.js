const $ = (sel) => document.querySelector(sel);
const log = $("#log");
let sessionId = null;

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res;
}
const json = (path, method, body) =>
  api(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then((r) => r.json());

function say(html, who = "bot") {
  const div = document.createElement("div");
  div.className = `msg ${who}`;
  div.innerHTML = html;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

// ---- knowledge base ----------------------------------------------------

async function loadForms() {
  const forms = await api("/api/forms").then((r) => r.json());
  $("#forms").innerHTML = forms.length
    ? forms.map((f) => `<li><div><strong>${esc(f.title)}</strong>
        <small>${esc(f.kind.replace("_", " "))} · ${f.field_count} fields</small>
        <small>${esc(f.description)}</small></div>
        <button data-del="${esc(f.id)}" title="Remove">✕</button></li>`).join("")
    : `<li class="status">No forms yet.</li>`;
}

function kbStatus(text, error = false) {
  $("#kb-status").textContent = text;
  $("#kb-status").className = "status" + (error ? " error" : "");
}

$("#forms").addEventListener("click", async (e) => {
  const id = e.target.dataset.del;
  if (id && confirm("Remove this form from the knowledge base?")) {
    await api(`/api/forms/${id}`, { method: "DELETE" });
    loadForms();
  }
});

$("#add-url").addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = e.target.url.value;
  kbStatus("Reading form…");
  try {
    const f = await json("/api/forms/url", "POST", { url });
    kbStatus(`Added "${f.title}" (${f.field_count} fields).`);
    e.target.reset();
    loadForms();
  } catch (err) { kbStatus(err.message, true); }
});

$("#add-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  kbStatus(`Reading ${file.name}…`);
  const body = new FormData();
  body.append("file", file);
  try {
    const f = await api("/api/forms/upload", { method: "POST", body }).then((r) => r.json());
    kbStatus(`Added "${f.title}" (${f.field_count} fields).`);
    loadForms();
  } catch (err) { kbStatus(err.message, true); }
  e.target.value = "";
});

// ---- Google sign-in (browser add-on) -------------------------------------

function loginStatus(text, error = false) {
  $("#login-status").innerHTML = esc(text);
  $("#login-status").className = "status" + (error ? " error" : "");
}

async function checkBrowser() {
  try {
    const { installed, hosted } = await api("/api/browser/status").then((r) => r.json());
    // Hosted: sign-in would open a window on the server, so hide it; prefilled links cover sign-in forms.
    if (hosted) $("#google-login").closest("section").hidden = true;
    else if (!installed) loginStatus("Browser add-on not installed (needed for Apps Script and sign-in forms). See README.");
  } catch {}
}

$("#google-login").addEventListener("click", async (e) => {
  const btn = e.target;
  btn.disabled = true;
  loginStatus("A browser window opened. Sign in to Google, then close that window.");
  try {
    const { signed_in } = await json("/api/browser/login", "POST", {});
    loginStatus(signed_in ? "Signed in to Google." : "The window closed before sign-in finished.", !signed_in);
  } catch (err) { loginStatus(err.message, true); }
  btn.disabled = false;
});

// ---- chat --------------------------------------------------------------

function renderQuestions(turn) {
  const items = turn.questions.map((q) => {
    const opts = q.options.length ? `<div class="opts">Options: ${q.options.map(esc).join(" · ")}</div>` : "";
    return `<li>${esc(q.question)}${q.required ? ' <span class="req">*</span>' : ""}${opts}</li>`;
  }).join("");
  say(`${md(turn.reply)}<ol>${items}</ol>
    <div class="hint">Answer them all in one message; numbered or free-form is fine. Say "skip" for any you want blank.</div>`);
}

function inputFor(f) {
  const name = `name="${esc(f.id)}"`;
  const v = f.value;
  if (f.type === "boolean") {
    return `<select ${name}><option value=""></option>
      <option value="yes" ${v === true ? "selected" : ""}>Yes</option>
      <option value="no" ${v === false ? "selected" : ""}>No</option></select>`;
  }
  if (f.options.length && f.type !== "checkbox") {
    return `<select ${name}><option value=""></option>${f.options.map((o) =>
      `<option ${o === v ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
  }
  const val = Array.isArray(v) ? v.join(", ") : v ?? "";
  if (f.type === "paragraph") return `<textarea ${name} rows="3">${esc(val)}</textarea>`;
  const type = { date: "date", time: "time", email: "email", number: "number" }[f.type] || "text";
  const hint = f.type === "checkbox" ? `<div class="opts">Comma-separated: ${f.options.map(esc).join(" · ")}</div>` : "";
  return `<input ${name} type="${type}" value="${esc(val)}">${hint}`;
}

function renderReview(turn) {
  const missing = new Set(turn.missing_required);
  const verb = turn.action === "submit" ? "Approve & submit" : "Approve & download";
  const box = say(`${md(turn.reply || "")}
    <p><strong>Review before I ${turn.action === "submit" ? "submit" : "fill the file"}.</strong> Edit anything that's off.</p>
    <form class="review">
      ${turn.fields.map((f) => `<div class="${missing.has(f.id) ? "missing" : ""}">
        <label>${esc(f.label)}${f.required ? ' <span class="req">*</span>' : ""}</label>${inputFor(f)}</div>`).join("")}
      <p class="error"></p>
      <button>${verb}</button>
      ${turn.prefill ? '<button type="button" class="secondary" data-prefill>Open prefilled in my browser</button>' : ""}
    </form>`);
  const form = box.querySelector("form");
  // For Google Forms that need sign-in: open a prefilled copy and submit it yourself.
  form.querySelector("[data-prefill]")?.addEventListener("click", async () => {
    const err = form.querySelector(".error");
    const win = window.open("", "_blank"); // open now, before awaits, so popup blockers allow it
    if (win) win.opener = null; // the Google page must not be able to reach back into this tab
    try {
      const updated = await json(`/api/chat/${sessionId}/answers`, "PUT", {
        answers: Object.fromEntries(new FormData(form)),
      });
      if (updated.rejected.length) {
        win?.close();
        box.remove();
        renderReview({ ...updated, reply: "Some values didn't fit the form; please fix the highlighted fields." });
        return;
      }
      const { url, reply } = await json(`/api/chat/${sessionId}/prefill`, "POST");
      if (win) win.location = url;
      else window.location = url;
      form.querySelectorAll("input,select,textarea,button").forEach((el) => (el.disabled = true));
      sessionId = null;
      say(md(reply));
    } catch (ex) {
      win?.close();
      err.textContent = ex.message;
    }
  });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button");
    const err = form.querySelector(".error");
    btn.disabled = true;
    err.textContent = "";
    try {
      const answers = Object.fromEntries(new FormData(form));
      const updated = await json(`/api/chat/${sessionId}/answers`, "PUT", { answers });
      if (updated.missing_required.length || updated.rejected.length) {
        box.remove();
        renderReview({ ...updated, reply: updated.rejected.length ? "Some values didn't fit the form; please fix the highlighted fields." : "A few required fields are still empty." });
        return;
      }
      const res = await api(`/api/chat/${sessionId}/submit`, { method: "POST" });
      if ((res.headers.get("content-type") || "").includes("application/json")) {
        const data = await res.json();
        if (data.stage === "review") {
          // The live form pre-filled things you weren't asked about: nothing was sent, review them.
          box.remove();
          renderReview(data);
          return;
        }
        say(md(data.reply));
      } else {
        const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") || "")?.[1] || "filled";
        const url = URL.createObjectURL(await res.blob());
        say(`Done. <a href="${url}" download="${esc(name)}">Download ${esc(name)}</a>`);
        Object.assign(document.createElement("a"), { href: url, download: name }).click();
      }
      form.querySelectorAll("input,select,textarea,button").forEach((el) => (el.disabled = true));
      sessionId = null;
    } catch (ex) {
      err.textContent = ex.message;
      btn.disabled = false;
    }
  });
}

function render(turn) {
  if (turn.stage === "no_match") return say(md(turn.reply));
  sessionId = turn.session_id;
  if (turn.stage === "asking") renderQuestions(turn);
  else if (turn.stage === "review") renderReview(turn);
}

$("#composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  const box = e.target.message;
  const message = box.value.trim();
  if (!message) return;
  say(esc(message), "me");
  box.value = "";
  const btn = e.target.querySelector("button");
  btn.disabled = true;
  const thinking = say('<span class="hint">Thinking…</span>');
  try {
    render(await json(sessionId ? `/api/chat/${sessionId}` : "/api/chat", "POST", { message }));
  } catch (err) {
    say(`<span class="error">${esc(err.message)}</span>`);
    if (/expired/.test(err.message)) sessionId = null;
  } finally {
    thinking.remove();
    btn.disabled = false;
  }
});

$("#composer textarea").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); e.target.form.requestSubmit(); }
});

loadForms();
checkBrowser();
