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
  overview: ["title.overview", "sub.overview"],
  operate: ["title.operate", "sub.operate"],
  agents: ["title.agents", "sub.agents"],
  ledger: ["title.ledger", "sub.ledger"],
  policy: ["title.policy", "sub.policy"],
};
const _goTab = goTab;
goTab = function (name) {
  _goTab(name);
  const k = TITLES[name] || [name, ""];
  $("view-title").textContent = t(k[0]); $("view-sub").textContent = t(k[1]);
};
if (["overview","operate","agents","ledger","policy"].includes(location.hash.slice(1))) goTab(location.hash.slice(1));
if (location.hash === "#verify" || location.hash === "#redteam") goTab("overview");

/* ---------- api + toast ---------- */
function apiToken() { try { return sessionStorage.getItem("prof_token") || ""; } catch { return ""; } }
function apiHeaders(extra) {
  const h = { ...(extra || {}) };
  const t = apiToken();
  if (t) h["authorization"] = "Bearer " + t;
  return h;
}
async function jget(p) {
  const r = await fetch(p, { headers: apiHeaders() });
  if (r.status === 401) { needToken(); throw new Error("unauthorized"); }
  if (!r.ok) throw new Error(p + " " + r.status);
  return r.json();
}
async function jpost(p, b) {
  const r = await fetch(p, { method: "POST", headers: apiHeaders({"content-type":"application/json"}), body: JSON.stringify(b) });
  if (r.status === 401) { needToken(); return { status: 401, body: { detail: "API token required — click the lock icon" } }; }
  const t = await r.json().catch(() => ({ ok:false, error:"bad response" }));
  return { status: r.status, body: t };
}
function needToken() {
  toast("err", t("t.token.need"), t("t.token.how"));
}
$("btn-key").onclick = () => {
  const cur = apiToken();
  const v = prompt("PROF API token (empty to clear):", cur);
  if (v === null) return;
  try {
    if (v.trim()) sessionStorage.setItem("prof_token", v.trim());
    else sessionStorage.removeItem("prof_token");
  } catch { /* private mode */ }
  $("btn-key").classList.toggle("set", !!apiToken());
  toast("ok", apiToken() ? t("t.token.saved") : t("t.token.cleared"), "");
  refresh();
};
if (apiToken()) $("btn-key").classList.add("set");
function toast(kind, title, msg) {
  const d = document.createElement("div");
  d.className = "toast " + (kind === "ok" ? "ok" : kind === "err" ? "err" : "");
  d.innerHTML = `<b>${esc(title)}</b><span>${esc(msg)}</span>`;
  $("toasts").appendChild(d);
  setTimeout(() => { d.style.opacity = "0"; setTimeout(() => d.remove(), 300); }, 5200);
}
function copyText(t, label) {
  navigator.clipboard.writeText(t).then(() => toast("ok", t("t.copied"), label || t("t.clipboard")),
    () => toast("err", t("t.copyfail"), t("t.noclip")));
}
const show = (id, o) => { $(id).textContent = typeof o === "string" ? o : JSON.stringify(o, null, 2); };

/* ---------- state ---------- */
let lastPermit = null, lastEntries = [], ledgerFilter = "all", areaHist = [], baseAllow = null, baseDeny = null;
let lastTasks = [];
let lastInboxCounts = {};
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
const ago = (ts) => { const s = Math.max(0, Date.now()/1000 - ts); return s < 60 ? Math.floor(s)+t("ago.s") : Math.floor(s/60)+t("ago.m"); };

async function refresh() {
  try {
    const [v, m, l] = await Promise.all([jget("/version"), jget("/metrics"), jget("/v1/ledger")]);
    $("health").innerHTML = '<span class="dot green"></span><span>' + t("st.online") + '</span>';
    $("h-version").textContent = "v" + (v.version || "?");
    $("ap-subject").textContent = v.approver_subject || "–";
    $("ap-source").textContent = v.key_source === "configured"
      ? t("key.managed")
      : t("key.ephemeral");
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
    $("sb-head").textContent = t("sb.head") + " " + String(v.ledger_head || "").slice(0, 22) + "…";
    $("k-ledger").textContent = m.ledger_entries ?? 0;
    $("k-policy").textContent = v.policy_id || "–";
    $("k-chain").textContent = l.ok ? t("chain.valid") : t("chain.invalid");
    $("k-chain").style.color = l.ok ? "var(--ok)" : "var(--bad)";
    donut(m.allow || 0, m.deny || 0);
    area({ a: m.allow || 0, d: m.deny || 0 });
    lastEntries = l.entries || [];
    renderFeed(); renderLedgerRows();
  } catch (e) {
    $("health").innerHTML = '<span class="dot red"></span>' + t("st.offline");
  }
}
function renderFeed() {
  if (!$("feed-live").checked) return;
  const items = lastEntries.slice(-12).reverse();
  $("feed").innerHTML = items.length ? items.map((e) =>
    `<li><span class="t">${ago(e.ts)}</span><span class="ev ev-${e.event}">${e.event}</span>` +
    `<span><b>${esc(e.action)}</b> · ${esc(e.resource)}<br><span class="mut">${esc((e.detail||"").slice(0,110))}</span></span></li>`
  ).join("") : `<li class="mut">${t("feed.empty")}</li>`;
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
  let p; try { p = JSON.parse($("e-permit").value); } catch { $("permit-info").innerHTML = t("permit.none"); return; }
  const left = Math.round(p.expiry - Date.now()/1000);
  const cls = left <= 0 ? "exp-dead" : left < 60 ? "exp-soon" : "exp-ok";
  const txt = left <= 0 ? t("exp.dead") : left < 60 ? `${t("exp.in")} ${left}${t("exp.s")}` : `${t("exp.valid")} · ${Math.floor(left/60)}${t("exp.m")} ${left%60}${t("exp.s")} ${t("exp.left")}`;
  $("permit-info").innerHTML =
    `subject <b>${esc(p.subject)}</b> · agent <b>${esc(p.agent)}</b><br>` +
    `<span class="mono">args ${esc((p.args_hash||"").slice(0,20))}… · nonce <span class="mono">${esc((p.nonce||"").slice(0,12))}…</span></span> · <span class="${cls}">${txt}</span>`;
}
$("e-permit").addEventListener("input", permitInfo);
setInterval(() => { if ($("tab-operate").classList.contains("on") && $("e-permit").value) permitInfo(); }, 5000);
$("btn-copy-permit").onclick = () => $("e-permit").value && copyText($("e-permit").value, t("btn.copy.permit"));
$("btn-copy-curl").onclick = () => {
  let args, permit;
  try { args = JSON.parse($("e-args").value); permit = JSON.parse($("e-permit").value); }
  catch { toast("err", t("t.nopermit"), t("t.signfirst")); return; }
  const body = JSON.stringify({ action: $("e-action").value, resource: $("e-resource").value, args, permit });
  copyText(`curl -s -X POST ${location.origin}/v1/execute -H 'content-type: application/json' -d '${body.replace(/'/g, "'\\''")}'`, t("btn.copy.curl"));
};

$("btn-approve").onclick = async () => {
  let args; try { args = JSON.parse($("a-args").value); } catch (e) { toast("err",t("t.badjson"),t("t.fixargs")); return; }
  const { status, body } = await jpost("/v1/approve", { agent: $("a-agent").value, action: $("a-action").value,
    resource: $("a-resource").value, args, ttl_s: +$("a-ttl").value || 300 });
  if (status === 200) {
    lastPermit = body;
    $("e-permit").value = JSON.stringify(body, null, 2); permitInfo();
    show("o-execute", t("t.signed")); 
    toast("ok", t("t.signed"), `${body.action} · ${body.resource}`);
  } else {
    show("o-execute", `HTTP ${status}\n` + JSON.stringify(body, null, 2));
    toast("err", t("t.denied.approve"), (body.detail || JSON.stringify(body)).slice(0, 160));
  }
  refresh();
};
$("btn-execute").onclick = async () => {
  let args, permit;
  try { args = JSON.parse($("e-args").value); } catch { toast("err",t("t.badjson"),t("t.fixargs")); return; }
  try { permit = JSON.parse($("e-permit").value); } catch { toast("err","No permit","sign a permit in step 1 first"); return; }
  show("o-execute", t("t.executing"));
  const { body } = await jpost("/v1/execute", { action: $("e-action").value, resource: $("e-resource").value, args, permit });
  show("o-execute", body);
  toast(body.ok ? "ok" : "err", body.ok ? t("t.allowed") : t("t.denied"),
    (body.decision || body.result && JSON.stringify(body.result) || "").toString().slice(0, 200));
  refresh();
};

/* ---------- verification (compact rows on Overview) ---------- */
const SCEN = [
  { id:"legit",  name:"Legit request",   desc:"Approved args executed exactly. Expect ALLOW." },
  { id:"tamper", name:"Args tamper",     desc:"Swap args after approval. Expect DENY." },
  { id:"replay", name:"Replay permit",   desc:"Reuse the single-use permit. Expect DENY." },
  { id:"expired",name:"Expired permit",  desc:"Approve with negative TTL. Expect DENY." },
  { id:"scope",  name:"Scope escalation",desc:"/tmp/** permit used on /etc/**. Expect DENY." },
];
function renderScenarios() {
  const rows = SCEN.map((s) =>
    '<div class="vrow" data-s="' + s.id + '" style="cursor:pointer">' +
    '<span class="vdot" id="vd-' + s.id + '"></span>' +
    '<span class="nm">' + esc(t("v." + s.id + ".n")) + '<small>' + esc(t("v." + s.id + ".d")) + '</small></span>' +
    '<span class="vverdict" id="v-' + s.id + '">' + esc(t("t.notrun")) + '</span></div>').join("");
  $("verify-mini").innerHTML = rows;
  document.querySelectorAll("#verify-mini .vrow").forEach((r) => (r.onclick = () => runScen(r.dataset.s)));
}
renderScenarios();
async function runScen(id) {
  const el = $("v-" + id), dot = $("vd-" + id);
  el.className = "vverdict"; el.textContent = t("t.running"); dot.className = "vdot run";
  const A = { agent: "agent:redteam", action: "tool.call", resource: "tool:crm.lookup", args: { customer: "acme-42" } };
  const ap = await jpost("/v1/approve", { ...A, ttl_s: id === "expired" ? -5 : 300 });
  if (ap.status !== 200) {
    el.className = "vverdict fail"; el.textContent = t("t.setup.fail"); dot.className = "vdot fail";
    return false;
  }
  const permit = ap.body; let ex;
  if (id === "legit") ex = await jpost("/v1/execute", { ...A, permit });
  else if (id === "tamper") ex = await jpost("/v1/execute", { action:A.action, resource:A.resource, args:{customer:"acme-42",admin:true}, permit });
  else if (id === "replay") { await jpost("/v1/execute", { ...A, permit }); ex = await jpost("/v1/execute", { ...A, permit }); }
  else if (id === "expired") ex = await jpost("/v1/execute", { ...A, permit });
  else ex = await jpost("/v1/execute", { action:"file.write", resource:"file:/etc/**", args:{path:"/etc/pwn",content:"x"}, permit });
  const want = id === "legit";
  const pass = !!ex.body.ok === want;
  el.className = "vverdict " + (pass ? "pass" : "fail");
  el.textContent = (pass ? "✓ " : "✕ ") + (ex.body.ok ? t("t.allowed") : t("t.denied"));
  dot.className = "vdot " + (pass ? "pass" : "fail");
  refresh(); return pass;
}
$("btn-run-all").onclick = async () => {
  let pass = 0;
  for (const s of SCEN) if (await runScen(s.id)) pass++;
  $("rt-summary").textContent = `${pass}/${SCEN.length} ` + t("t.scen.behaved");
  toast(pass === SCEN.length ? "ok" : "err", t("t.verify.done"), `${pass}/${SCEN.length} ` + t("t.as.expected"));
};

/* ---------- ledger export ---------- */
$("btn-export").onclick = () => {
  const blob = new Blob([JSON.stringify(lastEntries, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "prof-ledger.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  toast("ok", t("t.exported"), `${lastEntries.length} ` + t("t.exported.s"));
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
      `<button data-ap="${q.id}">${t("btn.approve.q")}</button><button data-dn="${q.id}">${t("btn.deny.q")}</button></li>`
    ).join("") : '<li class="mut">${t("pend.empty")}</li>';
    document.querySelectorAll("#pend-list [data-ap]").forEach((b) => (b.onclick = () => decideRequest(b.dataset.ap, true)));
    document.querySelectorAll("#pend-list [data-dn]").forEach((b) => (b.onclick = () => decideRequest(b.dataset.dn, false)));
  } catch { /* offline */ }
}
async function decideRequest(rid, approve) {
  const url = `/v1/requests/${rid}/${approve ? "approve" : "deny"}`;
  const { status, body } = await jpost(url, approve ? {} : { reason: "denied in console" });
  if (status === 200) {
    toast(approve ? "ok" : "err", approve ? t("t.approved") : t("t.hdenied"), rid);
    if (approve && body.permit) { lastPermit = body.permit; }
  } else {
    toast("err", t("t.decision.fail"), JSON.stringify(body).slice(0, 160));
  }
  loadPending(); refresh();
}
let reqTimer = null;
$("btn-request").onclick = async () => {
  let args; try { args = JSON.parse($("a-args").value); } catch { toast("err", t("t.badjson"), t("t.fixargs")); return; }
  const { status, body } = await jpost("/v1/requests", { agent: $("a-agent").value, action: $("a-action").value,
    resource: $("a-resource").value, args, ttl_s: +$("a-ttl").value || 300 });
  if (status !== 200) {
    $("req-status").textContent = (body.detail || JSON.stringify(body)).slice(0, 140);
    toast("err", t("t.req.rejected"), $("req-status").textContent);
    return;
  }
  const rid = body.id;
  $("req-status").textContent = `${rid} ` + t("req.pending");
  loadPending();
  clearInterval(reqTimer);
  reqTimer = setInterval(async () => {
    try {
      const q = await jget(`/v1/requests/${rid}`);
      if (q.status === "approved" && q.permit) {
        clearInterval(reqTimer);
        $("e-permit").value = JSON.stringify(q.permit, null, 2); permitInfo();
        $("req-status").textContent = `${rid} ` + t("req.approved.msg");
        toast("ok", t("t.approved"), rid);
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
async function loadLLM(quiet) {
  try {
    const s = await jget("/v1/llm/status");
    $("llm-provider").textContent = s.provider || "–";
    $("llm-url").textContent = s.base_url || "–";
    $("llm-model").textContent = s.model || "–";
    $("llm-key").textContent = s.key_present ? t("key.set") : s.needs_key ? t("key.missing") : t("key.local");
    const el = $("llm-state");
    el.textContent = s.reachable ? t("mcp.live") : t("mcp.down");
    el.classList.toggle("bad", !s.reachable);
    const pick = $("llm-pick"), cur = pick.value;
    pick.innerHTML = '<option value="">' + t("ag.gwdefault") + '</option>' +
      (s.models || []).map((m) => `<option value="${esc(m.id)}"${!m.tools ? ' data-tools="false"' : ''}>${esc(m.id)}</option>`).join("");
    if ([...pick.options].some((o) => o.value === cur)) pick.value = cur;
    const prov = $("llm-prov"), pcur = prov.value;
    prov.innerHTML = '<option value="">' + t("ag.gwdefault") + '</option>' +
      Object.keys(s.providers || {}).map((p) => `<option>${esc(p)}</option>`).join("");
    if ([...prov.options].some((o) => o.value === pcur)) prov.value = pcur;
    if (!prov.value && s.provider) prov.value = [...prov.options].some((o) => o.value === s.provider) ? s.provider : "";
    if (!s.reachable && !quiet) toast("err", t("t.llm.down"), (s.info || "").slice(0, 160));
  } catch { const el = $("llm-state"); el.textContent = t("mcp.down"); el.classList.add("bad"); }
}
function chosenModel() {
  const custom = $("llm-custom").value.trim();
  return custom || $("llm-pick").value || "";
}
async function loadModelsFor(provider) {
  const pick = $("llm-pick"), cur = pick.value;
  try {
    const s = await jget("/v1/llm/models" + (provider ? "?provider=" + encodeURIComponent(provider) : ""));
    pick.innerHTML = '<option value="">' + t("ag.gwdefault") + '</option>' +
      (s.models || []).map((m) => `<option value="${esc(m.id)}"${!m.tools ? ' data-tools="false"' : ''}>${esc(m.id)}</option>`).join("");
    if ([...pick.options].some((o) => o.value === cur)) pick.value = cur;
    if (s.fallback) toast("", t("t.catalog"), t("t.catalog.s"));
  } catch { /* keep previous list */ }
}
$("llm-prov").onchange = () => loadModelsFor($("llm-prov").value);
$("llm-pick").onchange = () => {
  const sel = $("llm-pick").options[$("llm-pick").selectedIndex];
  if (sel && sel.dataset.tools === "false") {
    toast("warn", t("model.notools"), t("model.notoolsdesc"));
  }
};
$("btn-llm-check").onclick = () => loadLLM(false);
$("btn-llm-save").onclick = async () => {
  const body = {};
  if ($("llm-prov").value) body.provider = $("llm-prov").value;
  if (chosenModel()) body.model = chosenModel();
  if (!body.provider && !body.model) { toast("err", t("t.nothing"), t("t.pickfirst")); return; }
  const sel = $("llm-pick").options[$("llm-pick").selectedIndex];
  if (sel && sel.dataset.tools === "false") {
    toast("err", t("model.notools"), t("model.notoolsdesc"));
    return;
  }
  const res = await jpost("/v1/llm/config", body);
  if (res.status !== 200) { toast("err", t("t.save.fail"), JSON.stringify(res.body).slice(0, 160)); return; }
  toast("ok", t("t.saved"), res.body.saved || "");
};
$("btn-agent-run").onclick = async () => {
  const task = $("agent-task").value.trim();
  if (!task) { toast("err", t("t.empty.task"), t("t.describe")); return; }
  const sel = $("llm-pick").options[$("llm-pick").selectedIndex];
  if (sel && sel.dataset.tools === "false") {
    toast("err", t("model.notools"), t("model.notoolsdesc"));
    return;
  }
  show("o-agent", t("agent.running"));
  $("agent-summary").textContent = "";
  const { status, body } = await jpost("/v1/agent/run", { task, max_steps: 8,
    human_approve: $("agent-human").checked, wait_approval: $("agent-wait").checked,
    approval_timeout_s: 120, provider_override: $("llm-prov").value || "",
    model_override: chosenModel() });
  if (status !== 200) {
    show("o-agent", `HTTP ${status}\n` + JSON.stringify(body, null, 2));
    toast("err", t("t.run.fail"), (body.detail || "").slice(0, 160));
    return;
  }
  $("agent-summary").textContent = `${t("legend.allowed")} ${body.allowed} · ${t("legend.denied")} ${body.denied}`;
  show("o-agent", `${t("agent.answer")}: ${body.answer}\n\n` + body.steps.map((s) =>
    `[${s.ok ? t("t.allowed") : t("t.denied")}] ${s.tool} — ${s.decision || ""}${s.ledger_seq !== undefined ? ` (ledger #${s.ledger_seq})` : ""}`).join("\n"));
  toast(body.denied && !body.allowed ? "err" : "ok", t("t.run.done"), `${t("legend.allowed")} ${body.allowed}, ${t("legend.denied")} ${body.denied}`);
  refresh();
};
/* ---------- agent task inbox (assign work to any connected agent) ---------- */
const INBOX_EV = { pending: "request", claimed: "approve", done: "allow", failed: "deny", cancelled: "deny" };
async function loadInbox() {
  try {
    const r = await jget("/v1/tasks?status=&limit=50");
    lastTasks = r.tasks || [];
    lastInboxCounts = r.counts || {};
    renderInbox(lastInboxCounts);
  } catch { /* offline */ }
}
function renderInbox(counts) {
  counts = counts || lastInboxCounts;
  const f = ($("inbox-agent-filter").value || "").trim().toLowerCase();
  let items = lastTasks;
  if (f) items = items.filter((x) =>
    (x.target_agent || "").toLowerCase().includes(f) || (x.claimed_by || "").toLowerCase().includes(f));
  const active = (counts.pending || 0) + (counts.claimed || 0);
  $("inbox-count").textContent = active ? active + " " + t("ag.inbox.active") : "";
  $("inbox-list").innerHTML = items.length ? items.slice(0, 20).map((x) => {
    const meta = [esc(x.id)];
    if (x.target_agent) meta.push("→ " + esc(x.target_agent));
    if (x.claimed_by) meta.push("· " + esc(x.claimed_by));
    if (x.result) meta.push("· " + esc(String(x.result).slice(0, 140)));
    if (x.error) meta.push("· ⚠ " + esc(String(x.error).slice(0, 120)));
    const open = x.status === "pending" || x.status === "claimed";
    return `<li><span class="ev ev-${INBOX_EV[x.status] || "request"}">${esc(x.status)}</span>` +
      `<span style="flex:1"><b>${esc(String(x.task).slice(0, 140))}</b><br>` +
      `<span class="mut">${meta.join(" ")}</span></span>` +
      (open ? `<button data-cancel="${esc(x.id)}">${t("btn.cancel")}</button>` : "");
  }).join("") : `<li class="mut">${t("inbox.empty")}</li>`;
  document.querySelectorAll("#inbox-list [data-cancel]").forEach((b) => (b.onclick = () => cancelTask(b.dataset.cancel)));
}
async function cancelTask(id) {
  const { status } = await jpost(`/v1/tasks/${id}/cancel`, {});
  toast(status === 200 ? "ok" : "err", status === 200 ? t("t.cancelled") : t("t.cancel.fail"), id);
  loadInbox();
}
$("btn-task-queue").onclick = async () => {
  const task = $("agent-task").value.trim();
  if (!task) { toast("err", t("t.empty.task"), t("t.describe")); return; }
  const target = ($("inbox-agent-filter").value || "").trim();
  const { status, body } = await jpost("/v1/tasks", { task, agent: target, max_steps: 8,
    human_approve: $("agent-human").checked, provider: $("llm-prov").value || "", model: chosenModel() });
  if (status !== 200) { toast("err", t("t.queue.fail"), (body.detail || JSON.stringify(body)).slice(0, 160)); return; }
  toast("ok", t("t.queued"), `${body.id}${target ? " → " + target : ""}`);
  loadInbox();
};
$("btn-inbox-refresh").onclick = loadInbox;
$("inbox-agent-filter").addEventListener("input", () => renderInbox());
$("btn-inbox-clear").onclick = async () => {
  const { status, body } = await jpost("/v1/tasks/clear", {});
  toast(status === 200 ? "ok" : "err", t("t.cleared"), `${(body && body.removed) || 0}`);
  loadInbox();
};
/* ---------- remote MCP self-test + per-agent panes ---------- */
$("mcp-url").value = location.origin + "/mcp";
$("btn-copy-mcp-url").onclick = () => copyText($("mcp-url").value, t("ag.mcp.url"));
$("btn-mcp-test").onclick = async () => {
  const { status, body } = await jpost("/mcp", { jsonrpc: "2.0", id: 1,
    method: "tools/list", params: {} }).catch((e) => ({ status: 0, body: e }));
  const el = $("mcp-state");
  const tools = body && body.result && body.result.tools;
  if (status === 200 && tools) {
    el.textContent = `${t("mcp.live")} · ${tools.length} ${t("mcp.tools")}`;
    el.classList.remove("bad");
    $("mcp-info").textContent = "Endpoint: " + tools.map((x) => x.name).join(", ");
  } else {
    el.textContent = "unreachable";
    el.classList.add("bad");
  }
};
const AGENTS = {
  dots: { title: "OpenAI Dots — custom MCP app", body:
    `1. Expose this gateway publicly: PROF_DOMAIN=… docker compose --profile edge up\n2. ChatGPT web → Settings → Apps → Advanced → Developer mode\n3. Plugins → + → Create MCP App (PROF, endpoint URL above, PROF_API_TOKEN as key)\n4. Verify: ask the dot to list PROF tools and look up acme-42\nNote: Pro workspaces are read-only for custom apps; writes need Business+.` },
  muse: { title: "Meta Muse — chat-built connector", body:
    `Paste into a Muse chat, replacing the URL with the endpoint above:\n\nBuild a custom connector to PROF, my proof-required execution gateway.\nIts MCP server is <URL> — hosted HTTPS, streamable HTTP.\nAuth is a static bearer token: ask me via the secure credential flow.\nTools: prof.approve, crm.lookup, file.write, payment.transfer (HIGH-RISK).\nConnect, test every tool, save as skill "PROF".\n\nPaste PROF_API_TOKEN only into the secure prompt, never the chat.` },
  claude: { title: "Claude Code", body:
    `MCP (any transport):\n  claude mcp add prof -- prof mcp\nRemote gateway instead:\n  claude mcp add --transport http prof <endpoint-URL>\n\nPreToolUse hook (auto-gates Write/Edit/Bash):\n  merge integrations/claude-code/settings-snippet.json into ~/.claude/settings.json\n  (hook: integrations/claude-code/prof-hook.py)` },
  codex: { title: "Codex CLI", body:
    `Append to ~/.codex/config.toml:\n  [mcp_servers.prof]\n  command = "prof"\n  args = ["mcp"]\nThen: "approve crm lookup for acme-42, then call it with the permit".` },
  gemini: { title: "Gemini CLI", body:
    `Merge into ~/.gemini/settings.json:\n  { "mcpServers": { "prof": { "command": "prof", "args": ["mcp"] } } }` },
  cursor: { title: "Cursor / Windsurf / Cline / VS Code / OpenCode", body:
    `Paste into the client's MCP config (.cursor/mcp.json, mcp_config.json, …):\n  { "mcpServers": { "prof": { "command": "prof", "args": ["mcp"] } } }\nRestart the client. (OpenCode: integrations/opencode/opencode.json)` },
  hook: { title: "Shell gate — any hook-capable agent", body:
    `PROF_ACTION=tool.call PROF_RESOURCE='tool:shell' PROF_ARGS='{"cmd":"deploy"}' \\\n  sh integrations/generic/prof-gate.sh   # exit 0 allow / 2 block\n\nEnd-to-end wrapper (high-tier needs --human-approve):\n  prof exec --action … --resource … --args … -- ./deploy.sh` },
};
function renderAgentPane(key) {
  const a = AGENTS[key];
  $("agent-pane").innerHTML =
    `<p class="mut"><b style="color:var(--txt)">${esc(a.title)}</b></p>` +
    `<pre class="out" id="agent-snip">${esc(a.body)}</pre>` +
    `<div class="row"><button id="btn-copy-ag" data-i18n="btn.copy.ag">Copy instructions</button></div>`;
  $("btn-copy-ag").onclick = () => copyText(a.body, t("ag.ext.note.short"));
}
document.querySelectorAll("#agent-tabs button").forEach((b) => (b.onclick = () => {
  document.querySelectorAll("#agent-tabs button").forEach((x) => x.classList.remove("on"));
  b.classList.add("on"); renderAgentPane(b.dataset.ag);
}));
renderAgentPane("dots");
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
    `<td class="mut">${esc((e.detail||"").slice(0,80))}</td><td>→</td></tr>`).join("") || '<tr><td colspan="7" class="mut">' + t("lg.empty") + '</td></tr>';
  document.querySelectorAll("#ledger-body tr[data-seq]").forEach((tr) => (tr.onclick = () => openEntry(+tr.dataset.seq)));
  const ok = lastEntries.length ? null : null;
  jget("/v1/ledger").then((l) => {
    const s = $("ledger-state");
    s.textContent = (l.ok ? "✓ " : "✕ ") + (l.message || "");
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
      `<td><span class="tier t-${r.tier}">${t("tier." + ({low:"low", medium:"med", high:"high"}[r.tier] || r.tier))}</span></td><td>${r.require_human ? t("yes") : t("no")}</td>` +
      `<td class="mono">${r.max_amount ?? "—"}</td></tr>`).join("");
  } catch (e) { /* offline */ }
}

/* ---------- boot (single) ---------- */
document.addEventListener("keydown", (e) => {
  if (e.target.matches("input,textarea,select")) return;
  const tabs = ["overview", "operate", "agents", "ledger", "policy"];
  if (e.key >= "1" && e.key <= "5") goTab(tabs[+e.key - 1]);
  if (e.key === "/") { e.preventDefault(); goTab("ledger"); setTimeout(() => $("ledger-q").focus(), 50); }
});
/* ---------- boot ---------- */
window.addEventListener("resize", () => areaHist.length && area(areaHist[areaHist.length - 1]));
let curAg = "dots";
const _renderAgentPane = renderAgentPane;
renderAgentPane = function (key) { curAg = key; _renderAgentPane(key); };
function applyLang(l) {
  setLang(l);
  const cur = document.querySelector("#tabs button.on");
  goTab(cur ? cur.dataset.tab : "overview");
  renderScenarios();
  renderAgentPane(curAg);
  if ($("e-permit").value) permitInfo(); else $("permit-info").innerHTML = t("permit.none");
  renderFeed(); renderLedgerRows(); loadPolicy(); loadPending(); loadLLM(true); loadInbox();
}
$("btn-lang").onclick = () => applyLang(PROF_LANG === "ko" ? "en" : "ko");
applyLang(PROF_LANG);
loadPolicy();
loadPending();
loadLLM(true);
loadInbox();
refresh();
setInterval(() => { if (!document.hidden) { refresh(); loadPending(); loadInbox(); } }, 4000);
setInterval(loadPolicy, 30000);
