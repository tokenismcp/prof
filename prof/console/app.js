/* PROF Console v2 — tabbed ops UI. Agent stays untrusted; all verdicts come from the gateway. */
"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

/* ---------- tabs (hash routing) ---------- */
const tabBtns = [...document.querySelectorAll("#tabs button")];
function goTab(name) {
  tabBtns.forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("on", s.id === "tab-" + name));
  if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
}
tabBtns.forEach((b) => (b.onclick = () => goTab(b.dataset.tab)));
const TITLES = {
  overview: ["Overview", "Live enforcement posture"],
  operate: ["Approve & Execute", "Sign a permit, then execute it — verified server-side"],
  verify: ["Verification", "Adversarial checks against real permits; the gateway decides"],
  agents: ["Agents", "LLM tasks and external agent connections, all proof-gated"],
  ledger: ["Ledger", "Tamper-evident audit trail, hash-linked"],
  policy: ["Policy", "Risk tiers currently enforced"],
};
const _goTab = goTab;
goTab = function (name) {
  _goTab(name);
  const t = TITLES[name] || [name, ""];
  $("view-title").textContent = t[0]; $("view-sub").textContent = t[1];
};
if (["overview","operate","verify","agents","ledger","policy"].includes(location.hash.slice(1))) goTab(location.hash.slice(1));
if (location.hash === "#redteam") goTab("verify");

/* ---------- api + toast ---------- */
async function jget(p) { const r = await fetch(p); if (!r.ok) throw new Error(p + " " + r.status); return r.json(); }
async function jpost(p, b) {
  const r = await fetch(p, { method: "POST", headers: {"content-type":"application/json"}, body: JSON.stringify(b) });
  const t = await r.json().catch(() => ({ ok:false, error:"bad response" }));
  return { status: r.status, body: t };
}
function toast(kind, title, msg) {
  const d = document.createElement("div");
  d.className = "toast " + (kind === "ok" ? "ok" : kind === "err" ? "err" : "");
  d.innerHTML = `<b>${esc(title)}</b><span>${esc(msg)}</span>`;
  $("toasts").appendChild(d);
  setTimeout(() => { d.style.opacity = "0"; setTimeout(() => d.remove(), 300); }, 5200);
}
function copyText(t, label) {
  navigator.clipboard.writeText(t).then(() => toast("ok", "Copied", label || "copied to clipboard"),
    () => toast("err", "Copy failed", "clipboard unavailable"));
}
const show = (id, o) => { $(id).textContent = typeof o === "string" ? o : JSON.stringify(o, null, 2); };

/* ---------- state ---------- */
let lastPermit = null, lastEntries = [], ledgerFilter = "all", areaHist = [], baseAllow = null, baseDeny = null;
const CIRC = 2 * Math.PI * 48;

/* ---------- overview ---------- */
function donut(allow, deny) {
  const tot = allow + deny;
  const frac = tot ? allow / tot : 1;
  $("donut-ok").style.strokeDashoffset = String(CIRC * (1 - frac));
  $("donut-bad").style.strokeDashoffset = String(-CIRC * frac);
  $("k-rate").textContent = tot ? Math.round(frac * 100) + "%" : "–";
}
function area(push) {
  areaHist.push(push); if (areaHist.length > 48) areaHist.shift();
  const c = $("area"); if (!c) return;
  const dpr = window.devicePixelRatio || 1, W = c.clientWidth || 600, H = 220;
  c.width = W * dpr; c.height = H * dpr;
  const x = c.getContext("2d"); x.scale(dpr, dpr);
  x.clearRect(0, 0, W, H);
  const mx = Math.max(1, ...areaHist.map((p) => p.a + p.d));
  const n = areaHist.length, step = W / 48;
  const y = (v) => H - 14 - (v / mx) * (H - 40);
  const series = (key, color, fill) => {
    x.beginPath();
    areaHist.forEach((p, i) => { const px = W - (n - 1 - i) * step; i ? x.lineTo(px, y(p[key])) : x.moveTo(px, y(p[key])); });
    x.strokeStyle = color; x.lineWidth = 2; x.stroke();
    x.lineTo(W - 0, H - 14); x.lineTo(W - (n - 1) * step, H - 14); x.closePath();
    const g = x.createLinearGradient(0, 0, 0, H); g.addColorStop(0, fill); g.addColorStop(1, "rgba(255,255,255,0)");
    x.fillStyle = g; x.fill();
  };
  x.strokeStyle = "#e6ecf6"; x.lineWidth = 1;
  [0.33, 0.66].forEach((f) => { x.beginPath(); x.moveTo(0, H * f); x.lineTo(W, H * f); x.stroke(); });
  series("a", "#15803d", "rgba(21,128,61,.18)");
  series("d", "#dc2645", "rgba(220,38,69,.14)");
}
const ago = (ts) => { const s = Math.max(0, Date.now()/1000 - ts); return s < 60 ? Math.floor(s)+"s ago" : Math.floor(s/60)+"m ago"; };

async function refresh() {
  try {
    const [v, m, l] = await Promise.all([jget("/version"), jget("/metrics"), jget("/v1/ledger")]);
    $("health").innerHTML = '<span class="dot green"></span><span>online</span>';
    $("h-version").textContent = "v" + (v.version || "?");
    $("ap-subject").textContent = v.approver_subject || "–";
    $("ap-source").textContent = v.key_source === "configured"
      ? "managed key (secret manager / HSM)"
      : "ephemeral key (single process)";
    $("ap-pubkey").textContent = "computing…";
    fingerprint(v.approver_pubkey || "").then((fp) => { $("ap-pubkey").textContent = fp; });
    $("k-allow").textContent = m.allow ?? 0;
    $("k-deny").textContent = m.deny ?? 0;
    $("lg-allow").textContent = m.allow ?? 0;
    $("lg-deny").textContent = m.deny ?? 0;
    if (baseAllow === null) { baseAllow = m.allow || 0; baseDeny = m.deny || 0; }
    const da = (m.allow || 0) - baseAllow, dd = (m.deny || 0) - baseDeny;
    const dA = $("d-allow"), dD = $("d-deny");
    dA.textContent = "+" + da; dA.className = "delta" + (da ? " up-ok" : "");
    dD.textContent = "+" + dd; dD.className = "delta" + (dd ? " up-bad" : "");
    $("sb-head").textContent = "ledger head " + String(v.ledger_head || "").slice(0, 22) + "…";
    $("k-ledger").textContent = m.ledger_entries ?? 0;
    $("k-policy").textContent = v.policy_id || "–";
    $("k-chain").textContent = "chain: " + (l.ok ? "valid ✓" : "INVALID ✕");
    $("k-chain").style.color = l.ok ? "var(--ok)" : "var(--bad)";
    donut(m.allow || 0, m.deny || 0);
    area({ a: m.allow || 0, d: m.deny || 0 });
    lastEntries = l.entries || [];
    renderFeed(); renderLedgerRows();
  } catch (e) {
    $("health").innerHTML = '<span class="dot red"></span>unreachable';
  }
}
function renderFeed() {
  if (!$("feed-live").checked) return;
  const items = lastEntries.slice(-12).reverse();
  $("feed").innerHTML = items.length ? items.map((e) =>
    `<li><span class="t">${ago(e.ts)}</span><span class="ev ev-${e.event}">${e.event}</span>` +
    `<span><b>${esc(e.action)}</b> · ${esc(e.resource)}<br><span class="mut">${esc((e.detail||"").slice(0,110))}</span></span></li>`
  ).join("") : '<li class="mut">no events yet</li>';
}

/* key fingerprint via WebCrypto */
async function fingerprint(b64) {
  try {
    const raw = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const d = await crypto.subtle.digest("SHA-256", raw);
    return "sha256:" + [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 24) + "…";
  } catch { return "–"; }
}

/* ---------- operate ---------- */
const PRESETS = {
  "tool.call": { r: "tool:crm.lookup", a: { customer: "acme-42" } },
  "file.write": { r: "file:/tmp/**", a: { path: "/tmp/prof-demo/notes.txt", content: "hello prof\n" } },
  "payment.transfer": { r: "account:krw-1", a: { to: "acct-7", amount: 50000, idempotency_key: "console-001" } },
};
$("a-action").onchange = () => {
  const p = PRESETS[$("a-action").value];
  $("a-resource").value = p.r; $("a-args").value = JSON.stringify(p.a, null, 2);
  $("e-action").value = $("a-action").value; $("e-resource").value = p.r; $("e-args").value = JSON.stringify(p.a, null, 2);
};
function permitInfo() {
  let p; try { p = JSON.parse($("e-permit").value); } catch { $("permit-info").innerHTML = "no permit loaded"; return; }
  const left = Math.round(p.expiry - Date.now()/1000);
  const cls = left <= 0 ? "exp-dead" : left < 60 ? "exp-soon" : "exp-ok";
  const txt = left <= 0 ? "EXPIRED" : left < 60 ? `expires in ${left}s` : `valid · ${Math.floor(left/60)}m ${left%60}s left`;
  $("permit-info").innerHTML =
    `subject <b>${esc(p.subject)}</b> · agent <b>${esc(p.agent)}</b><br>` +
    `<span class="mono">args ${esc((p.args_hash||"").slice(0,20))}… · nonce <span class="mono">${esc((p.nonce||"").slice(0,12))}…</span></span> · <span class="${cls}">${txt}</span>`;
}
$("e-permit").addEventListener("input", permitInfo);
setInterval(() => { if ($("tab-operate").classList.contains("on") && $("e-permit").value) permitInfo(); }, 5000);
$("btn-copy-permit").onclick = () => $("e-permit").value && copyText($("e-permit").value, "permit JSON copied");
$("btn-copy-curl").onclick = () => {
  let args, permit;
  try { args = JSON.parse($("e-args").value); permit = JSON.parse($("e-permit").value); }
  catch { toast("err", "No permit", "sign a permit in step 1 first"); return; }
  const body = JSON.stringify({ action: $("e-action").value, resource: $("e-resource").value, args, permit });
  copyText(`curl -s -X POST ${location.origin}/v1/execute -H 'content-type: application/json' -d '${body.replace(/'/g, "'\\''")}'`, "curl command copied");
};

$("btn-approve").onclick = async () => {
  let args; try { args = JSON.parse($("a-args").value); } catch (e) { toast("err","Bad JSON","fix Args JSON"); return; }
  const { status, body } = await jpost("/v1/approve", { agent: $("a-agent").value, action: $("a-action").value,
    resource: $("a-resource").value, args, ttl_s: +$("a-ttl").value || 300 });
  if (status === 200) {
    lastPermit = body;
    $("e-permit").value = JSON.stringify(body, null, 2); permitInfo();
    show("o-execute", "permit signed — review it above, then Execute with proof.");
    toast("ok", "Permit signed", `${body.action} · ${body.resource}`);
  } else {
    show("o-execute", `HTTP ${status}\n` + JSON.stringify(body, null, 2));
    toast("err", "Approve denied", (body.detail || JSON.stringify(body)).slice(0, 160));
  }
  refresh();
};
$("btn-execute").onclick = async () => {
  let args, permit;
  try { args = JSON.parse($("e-args").value); } catch { toast("err","Bad JSON","fix Args JSON"); return; }
  try { permit = JSON.parse($("e-permit").value); } catch { toast("err","No permit","sign a permit in step 1 first"); return; }
  show("o-execute", "executing…");
  const { body } = await jpost("/v1/execute", { action: $("e-action").value, resource: $("e-resource").value, args, permit });
  show("o-execute", body);
  toast(body.ok ? "ok" : "err", body.ok ? "ALLOWED" : "DENIED",
    (body.decision || body.result && JSON.stringify(body.result) || "").toString().slice(0, 200));
  refresh();
};

/* ---------- red team ---------- */
const SCEN = [
  { id:"legit",  name:"Legit request",   desc:"Approved args executed exactly. Expect ALLOW.", attack:"allow" },
  { id:"tamper", name:"Args tamper",     desc:"Swap args after approval (privilege/amount). Expect DENY.", attack:"deny" },
  { id:"replay", name:"Replay permit",   desc:"Reuse the same single-use permit. Expect DENY.", attack:"deny" },
  { id:"expired",name:"Expired permit",  desc:"Approve with negative TTL, then execute. Expect DENY.", attack:"deny" },
  { id:"scope",  name:"Scope escalation",desc:"Approved /tmp/** executed against /etc/**. Expect DENY.", attack:"deny" },
];
$("scenarios").innerHTML = SCEN.map((s) =>
  `<div class="scn"><h3>${s.name}</h3><p>${s.desc}</p><div class="verdict" id="v-${s.id}">not run</div><button data-s="${s.id}">Run</button></div>`).join("");
document.querySelectorAll("#scenarios button").forEach((b) => (b.onclick = () => runScen(b.dataset.s)));
async function runScen(id) {
  const el = $("v-" + id); el.className = "verdict run"; el.textContent = "running…";
  const A = { agent: "agent:redteam", action: "tool.call", resource: "tool:crm.lookup", args: { customer: "acme-42" } };
  const ap = await jpost("/v1/approve", { ...A, ttl_s: id === "expired" ? -5 : 300 });
  if (ap.status !== 200) { el.className = "verdict fail"; el.textContent = "setup failed"; return false; }
  const permit = ap.body; let ex;
  if (id === "legit") ex = await jpost("/v1/execute", { ...A, permit });
  else if (id === "tamper") ex = await jpost("/v1/execute", { action:A.action, resource:A.resource, args:{customer:"acme-42",admin:true}, permit });
  else if (id === "replay") { await jpost("/v1/execute", { ...A, permit }); ex = await jpost("/v1/execute", { ...A, permit }); }
  else if (id === "expired") ex = await jpost("/v1/execute", { ...A, permit });
  else ex = await jpost("/v1/execute", { action:"file.write", resource:"file:/etc/**", args:{path:"/etc/pwn",content:"x"}, permit });
  const want = id === "legit";
  const pass = !!ex.body.ok === want;
  el.className = "verdict " + (pass ? "pass" : "fail");
  el.textContent = (pass ? "✓ " : "✕ ") + (ex.body.ok ? "ALLOWED" : "DENIED");
  refresh(); return pass;
}
$("btn-run-all").onclick = async () => {
  let pass = 0;
  for (const s of SCEN) if (await runScen(s.id)) pass++;
  $("rt-summary").textContent = `${pass}/${SCEN.length} scenarios behaved as expected`;
  toast(pass === SCEN.length ? "ok" : "err", "Verification complete", `${pass}/${SCEN.length} as expected`);
};

/* ---------- ledger export ---------- */
$("btn-export").onclick = () => {
  const blob = new Blob([JSON.stringify(lastEntries, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "prof-ledger.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  toast("ok", "Exported", `${lastEntries.length} ledger entries downloaded`);
};

/* ---------- human approval queue ---------- */
async function loadPending() {
  try {
    const r = await jget("/v1/requests?status=pending");
    const items = r.requests || [];
    $("pend-count").textContent = items.length ? `${items.length} waiting` : "";
    $("pend-list").innerHTML = items.length ? items.slice(0, 5).map((q) =>
      `<li><span class="ev ev-request">request</span>` +
      `<span style="flex:1"><b>${esc(q.action)}</b> · ${esc(q.resource)}<br>` +
      `<span class="mut">${esc(q.agent)} · ${esc(JSON.stringify(q.args)).slice(0, 90)}</span></span>` +
      `<button data-ap="${q.id}">Approve</button><button data-dn="${q.id}">Deny</button></li>`
    ).join("") : '<li class="mut">none pending</li>';
    document.querySelectorAll("#pend-list [data-ap]").forEach((b) => (b.onclick = () => decideRequest(b.dataset.ap, true)));
    document.querySelectorAll("#pend-list [data-dn]").forEach((b) => (b.onclick = () => decideRequest(b.dataset.dn, false)));
  } catch { /* offline */ }
}
async function decideRequest(rid, approve) {
  const url = `/v1/requests/${rid}/${approve ? "approve" : "deny"}`;
  const { status, body } = await jpost(url, approve ? {} : { reason: "denied in console" });
  if (status === 200) {
    toast(approve ? "ok" : "err", approve ? "Approved & signed" : "Denied", rid);
    if (approve && body.permit) { lastPermit = body.permit; }
  } else {
    toast("err", "Decision failed", JSON.stringify(body).slice(0, 160));
  }
  loadPending(); refresh();
}
let reqTimer = null;
$("btn-request").onclick = async () => {
  let args; try { args = JSON.parse($("a-args").value); } catch { toast("err", "Bad JSON", "fix Args JSON"); return; }
  const { status, body } = await jpost("/v1/requests", { agent: $("a-agent").value, action: $("a-action").value,
    resource: $("a-resource").value, args, ttl_s: +$("a-ttl").value || 300 });
  if (status !== 200) {
    $("req-status").textContent = (body.detail || JSON.stringify(body)).slice(0, 140);
    toast("err", "Request rejected", $("req-status").textContent);
    return;
  }
  const rid = body.id;
  $("req-status").textContent = `${rid} pending — waiting for approver…`;
  loadPending();
  clearInterval(reqTimer);
  reqTimer = setInterval(async () => {
    try {
      const q = await jget(`/v1/requests/${rid}`);
      if (q.status === "approved" && q.permit) {
        clearInterval(reqTimer);
        $("e-permit").value = JSON.stringify(q.permit, null, 2); permitInfo();
        $("req-status").textContent = `${rid} approved — permit loaded below.`;
        toast("ok", "Human approved", rid);
        refresh();
      } else if (q.status === "denied") {
        clearInterval(reqTimer);
        $("req-status").textContent = `${rid} denied: ${q.deny_reason || ""}`;
        toast("err", "Human denied", rid);
      }
    } catch { clearInterval(reqTimer); }
  }, 2000);
};

/* ---------- agents: LLM + external connections ---------- */
async function loadLLM() {
  try {
    const s = await jget("/v1/llm/status");
    $("llm-url").textContent = s.base_url || "–";
    $("llm-model").textContent = s.model || "–";
    const el = $("llm-state");
    el.textContent = s.reachable ? "reachable" : "unreachable";
    el.classList.toggle("bad", !s.reachable);
    if (!s.reachable) toast("err", "LLM unreachable", (s.info || "").slice(0, 160));
  } catch { const el = $("llm-state"); el.textContent = "unreachable"; el.classList.add("bad"); }
}
$("btn-llm-check").onclick = loadLLM;
$("btn-agent-run").onclick = async () => {
  const task = $("agent-task").value.trim();
  if (!task) { toast("err", "Empty task", "describe what the agent should do"); return; }
  show("o-agent", "running model → permit → execution loop…");
  $("agent-summary").textContent = "";
  const { status, body } = await jpost("/v1/agent/run", { task, max_steps: 8, human_approve: $("agent-human").checked });
  if (status !== 200) {
    show("o-agent", `HTTP ${status}\n` + JSON.stringify(body, null, 2));
    toast("err", "Agent run failed", (body.detail || "").slice(0, 160));
    return;
  }
  $("agent-summary").textContent = `allowed ${body.allowed} · denied ${body.denied}`;
  show("o-agent", `ANSWER: ${body.answer}\n\n` + body.steps.map((s) =>
    `[${s.ok ? "ALLOW" : "DENY"}] ${s.tool} — ${s.decision || ""}${s.ledger_seq !== undefined ? ` (ledger #${s.ledger_seq})` : ""}`).join("\n"));
  toast(body.denied && !body.allowed ? "err" : "ok", "Agent run finished", `allowed ${body.allowed}, denied ${body.denied}`);
  refresh();
};
$("snip-mcp").value = '{\n  "mcpServers": {\n    "prof": { "command": "prof", "args": ["mcp"] }\n  }\n}';
$("btn-copy-mcp").onclick = () => copyText($("snip-mcp").value, "MCP JSON copied — use install.sh for your absolute path");
$("btn-copy-hook").onclick = () => copyText($("snip-hook").value, "hook command copied");
document.querySelectorAll("#ledger-filter button").forEach((b) => (b.onclick = () => {
  document.querySelectorAll("#ledger-filter button").forEach((x) => x.classList.remove("on"));
  b.classList.add("on"); ledgerFilter = b.dataset.f; renderLedgerRows();
}));
$("ledger-q").addEventListener("input", renderLedgerRows);
$("btn-ledger").onclick = refresh;
function renderLedgerRows() {
  const q = ($("ledger-q").value || "").toLowerCase();
  const rows = lastEntries.slice().reverse().filter((e) =>
    (ledgerFilter === "all" || e.event === ledgerFilter) &&
    (!q || [e.agent, e.action, e.resource, e.detail, String(e.seq)].join(" ").toLowerCase().includes(q)));
  $("ledger-body").innerHTML = rows.slice(0, 80).map((e) =>
    `<tr data-seq="${e.seq}"><td class="mono">${e.seq}</td><td><span class="ev ev-${e.event}">${e.event}</span></td>` +
    `<td>${esc(e.action)}</td><td>${esc(e.resource)}</td><td>${esc(e.agent)}</td>` +
    `<td class="mut">${esc((e.detail||"").slice(0,80))}</td><td>→</td></tr>`).join("") || '<tr><td colspan="7" class="mut">no entries match</td></tr>';
  document.querySelectorAll("#ledger-body tr[data-seq]").forEach((tr) => (tr.onclick = () => openEntry(+tr.dataset.seq)));
  const ok = lastEntries.length ? null : null;
  jget("/v1/ledger").then((l) => {
    const s = $("ledger-state");
    s.textContent = (l.ok ? "✓ valid · " : "✕ INVALID · ") + (l.message || "");
    s.classList.toggle("bad", !l.ok);
  }).catch(() => {});
}
function openEntry(seq) {
  const e = lastEntries.find((x) => x.seq === seq); if (!e) return;
  $("d-seq").textContent = "#" + e.seq;
  $("d-body").textContent = JSON.stringify(e, null, 2);
  $("d-chain").innerHTML = `prev <span class="hash">${esc((e.prev_hash||"").slice(0,26))}…</span><br>self <span class="hash">${esc((e.entry_hash||"").slice(0,26))}…</span>`;
  $("drawer").classList.add("on"); $("scrim").classList.add("on");
}
$("d-close").onclick = $("scrim").onclick = () => { $("drawer").classList.remove("on"); $("scrim").classList.remove("on"); };

/* ---------- policy ---------- */
async function loadPolicy() {
  try {
    const p = await jget("/v1/policy");
    $("policy-id").textContent = p.policy_id;
    $("policy-default").textContent = p.default_tier;
    $("policy-body").innerHTML = (p.rules || []).map((r) =>
      `<tr><td class="mono">${esc(r.action)}</td><td class="mono">${esc(r.resource)}</td>` +
      `<td><span class="tier t-${r.tier}">${r.tier}</span></td><td>${r.require_human ? "yes" : "no"}</td>` +
      `<td class="mono">${r.max_amount ?? "—"}</td></tr>`).join("");
  } catch (e) { /* offline */ }
}

/* ---------- boot (single) ---------- */
document.addEventListener("keydown", (e) => {
  if (e.target.matches("input,textarea,select")) return;
  const tabs = ["overview", "operate", "verify", "agents", "ledger", "policy"];
  if (e.key >= "1" && e.key <= "6") goTab(tabs[+e.key - 1]);
  if (e.key === "/") { e.preventDefault(); goTab("ledger"); setTimeout(() => $("ledger-q").focus(), 50); }
});
/* ---------- boot ---------- */
window.addEventListener("resize", () => areaHist.length && area(areaHist[areaHist.length - 1]));
loadPolicy();
loadPending();
loadLLM();
refresh();
setInterval(() => { if (!document.hidden) { refresh(); loadPending(); } }, 4000);
setInterval(loadPolicy, 30000);
