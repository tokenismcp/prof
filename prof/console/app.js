/* PROF Console — talks to the Gateway REST API. No secrets here; agent is untrusted. */
const $ = (id) => document.getElementById(id);
let lastPermit = null;

async function jget(p) { const r = await fetch(p); return r.json(); }
async function jpost(p, b) {
  const r = await fetch(p, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });
  const t = await r.json().catch(() => ({ ok: false, error: "bad response" }));
  return { status: r.status, body: t };
}
const show = (id, o) => { $(id).textContent = typeof o === "string" ? o : JSON.stringify(o, null, 2); };
const parse = (id) => { try { return JSON.parse($(id).value); } catch (e) { show("o-execute", "bad JSON: " + e); return null; } };

async function refresh() {
  try {
    const [v, m, l] = await Promise.all([jget("/version"), jget("/metrics"), jget("/v1/ledger")]);
    $("health").innerHTML = '<span class="dot green"></span> gateway online';
    $("c-version").textContent = v.version || "–";
    $("c-policy").textContent = v.policy_id || "–";
    $("c-allow").textContent = m.allow ?? "–";
    $("c-deny").textContent = m.deny ?? "–";
    $("c-ledger").textContent = m.ledger_entries ?? "–";
    $("c-chain").textContent = (l.ok ? "valid · " : "INVALID · ") + (l.message || "");
    renderLedger(l.entries || []);
  } catch (e) {
    $("health").innerHTML = '<span class="dot red"></span> gateway unreachable';
  }
  try {
    const p = await jget("/v1/policy");
    const tb = document.querySelector("#t-policy tbody");
    tb.innerHTML = (p.rules || []).map((r) =>
      `<tr><td>${r.action}</td><td>${r.resource}</td><td>${r.tier}</td><td>${r.require_human ? "yes" : "no"}</td></tr>`).join("");
  } catch (e) { /* ignore */ }
}

function renderLedger(entries) {
  const tb = document.querySelector("#t-ledger tbody");
  tb.innerHTML = entries.slice(-30).reverse().map((e) =>
    `<tr><td>${e.seq}</td><td class="ev-${e.event}">${e.event}</td><td>${e.action}</td><td>${e.resource}</td><td>${e.agent}</td><td>${(e.detail || "").slice(0, 90)}</td></tr>`).join("");
}

$("btn-approve").onclick = async () => {
  const args = parse("a-args"); if (!args) { show("o-approve", "fix Args JSON"); return; }
  const { status, body } = await jpost("/v1/approve", {
    agent: $("a-agent").value, action: $("a-action").value,
    resource: $("a-resource").value, args, ttl_s: +$("a-ttl").value || 300,
  });
  show("o-approve", `HTTP ${status}\n` + JSON.stringify(body, null, 2));
  if (status === 200) { lastPermit = body; $("e-permit").value = JSON.stringify(body, null, 2); }
};
$("btn-use-last").onclick = () => { if (lastPermit) $("e-permit").value = JSON.stringify(lastPermit, null, 2); };
$("btn-execute").onclick = async () => {
  const args = parse("e-args"); if (!args) return;
  let permit; try { permit = JSON.parse($("e-permit").value); } catch (e) { show("o-execute", "paste a permit first"); return; }
  const { body } = await jpost("/v1/execute", { action: $("e-action").value, resource: $("e-resource").value, args, permit });
  show("o-execute", body);
  refresh();
};
$("a-action").onchange = () => {
  const m = { "tool.call": "tool:crm.lookup", "file.write": "file:/tmp/**", "payment.transfer": "account:krw-1" };
  $("a-resource").value = m[$("a-action").value] || "";
  $("e-action").value = $("a-action").value; $("e-resource").value = $("a-resource").value;
};

async function attack(kind) {
  const a = await jpost("/v1/approve", { agent: "agent:redteam", action: "tool.call", resource: "tool:crm.lookup", args: { customer: "acme-42" }, ttl_s: 300 });
  if (a.status !== 200) { show("o-attacks", a.body); return; }
  const permit = a.body;
  let exec;
  if (kind === "legit") exec = await jpost("/v1/execute", { action: "tool.call", resource: "tool:crm.lookup", args: { customer: "acme-42" }, permit });
  if (kind === "tamper") exec = await jpost("/v1/execute", { action: "tool.call", resource: "tool:crm.lookup", args: { customer: "acme-42", admin: true }, permit });
  if (kind === "replay") {
    await jpost("/v1/execute", { action: "tool.call", resource: "tool:crm.lookup", args: { customer: "acme-42" }, permit });
    exec = await jpost("/v1/execute", { action: "tool.call", resource: "tool:crm.lookup", args: { customer: "acme-42" }, permit });
  }
  show("o-attacks", `${kind}: ` + JSON.stringify(exec.body, null, 2));
  refresh();
}
$("btn-legit").onclick = () => attack("legit");
$("btn-tamper").onclick = () => attack("tamper");
$("btn-replay").onclick = () => attack("replay");
$("btn-ledger").onclick = async () => {
  const l = await jget("/v1/ledger");
  $("ledger-msg").textContent = l.message || "";
  renderLedger(l.entries || []);
};

refresh();
setInterval(refresh, 5000);
