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
if (["overview","operate","redteam","ledger","policy"].includes(location.hash.slice(1))) goTab(location.hash.slice(1));
$("btn-go-operate").onclick = () => goTab("operate");

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
let lastPermit = null, lastEntries = [], ledgerFilter = "all", sparkHist = [];
const CIRC = 2 * Math.PI * 48;

/* ---------- overview ---------- */
function donut(allow, deny) {
  const tot = allow + deny;
  const frac = tot ? allow / tot : 1;
  $("donut-ok").style.strokeDashoffset = String(CIRC * (1 - frac));
  $("donut-bad").style.strokeDashoffset = String(-CIRC * frac);
  $("k-rate").textContent = tot ? Math.round(frac * 100) + "%" : "–";
}
function spark(push) {
  sparkHist.push(push); if (sparkHist.length > 40) sparkHist.shift();
  const c = $("spark"), x = c.getContext("2d"), W = c.width, H = c.height;
  x.clearRect(0, 0, W, H);
  const mx = Math.max(1, ...sparkHist.map((p) => p.a + p.d));
  const n = sparkHist.length;
  sparkHist.forEach((p, i) => {
    const bw = W / 40, bx = W - (n - i) * bw;
    const ah = (p.a / mx) * (H - 4), dh = (p.d / mx) * (H - 4);
    x.fillStyle = "#22c55e"; x.fillRect(bx, H - ah, bw - 2, ah);
    x.fillStyle = "#ff5470"; x.fillRect(bx, H - ah - dh, bw - 2, Math.max(1, dh));
  });
}
const ago = (ts) => { const s = Math.max(0, Date.now()/1000 - ts); return s < 60 ? Math.floor(s)+"s ago" : Math.floor(s/60)+"m ago"; };

async function refresh() {
  try {
    const [v, m, l] = await Promise.all([jget("/version"), jget("/metrics"), jget("/v1/ledger")]);
    $("health").innerHTML = '<span class="dot green"></span>online';
    $("h-version").textContent = "v" + (v.version || "?");
    $("k-allow").textContent = m.allow ?? 0;
    $("k-deny").textContent = m.deny ?? 0;
    $("k-ledger").textContent = m.ledger_entries ?? 0;
    $("k-policy").textContent = v.policy_id || "–";
    $("k-chain").textContent = "chain: " + (l.ok ? "valid ✓" : "INVALID ✕");
    $("k-chain").style.color = l.ok ? "var(--ok)" : "var(--bad)";
    donut(m.allow || 0, m.deny || 0);
    spark({ a: m.allow || 0, d: m.deny || 0 });
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
  ).join("") : '<li class="mut">no events yet — run the demo</li>';
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
  toast(pass === SCEN.length ? "ok" : "err", "Red team complete", `${pass}/${SCEN.length} as expected`);
};

/* ---------- full demo ---------- */
$("btn-full-demo").onclick = async () => {
  show("o-demo", "running…");
  const lines = [];
  for (const s of SCEN.slice(0, 4)) { const ok = await runScen(s.id); lines.push(`${ok ? "✓" : "✕"} ${s.name}`); }
  goTab("redteam");
  show("o-demo", lines.join("\n"));
};

/* ---------- ledger ---------- */
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

/* ---------- boot ---------- */
loadPolicy();
refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 4000);
setInterval(loadPolicy, 30000);
