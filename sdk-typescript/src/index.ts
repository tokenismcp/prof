// Minimal PROF Gateway client (fetch-based, zero deps).
export interface Permit { [k: string]: unknown; nonce: string }
export class ProfClient {
  constructor(private base = "http://127.0.0.1:8091") {}
  async approve(body: Record<string, unknown>): Promise<Permit> {
    const r = await fetch(`${this.base}/v1/approve`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error(`approve denied: ${await r.text()}`);
    return r.json();
  }
  async execute(body: Record<string, unknown>): Promise<unknown> {
    const r = await fetch(`${this.base}/v1/execute`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    return r.json();
  }
}
