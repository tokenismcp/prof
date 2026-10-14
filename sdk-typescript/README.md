# @prof/sdk (TypeScript) — Beta track

Parity client for the PROF Gateway (`/v1/approve`, `/v1/execute`). Python SDK is canonical in v0.1.

```ts
import { ProfClient } from "@prof/sdk";
const prof = new ProfClient("http://127.0.0.1:8091");
const permit = await prof.approve({ agent: "agent:web", action: "tool.call", resource: "tool:crm.lookup", args: { customer: "acme-42" } });
const res = await prof.execute({ action: "tool.call", resource: "tool:crm.lookup", args: { customer: "acme-42" }, permit });
```

See `src/index.ts`.
