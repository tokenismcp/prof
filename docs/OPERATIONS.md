# PROF Operations (production runbook)

## Deploy (compose, recommended for v0.1)

```sh
cp configs/prof.env.example configs/prof.env   # fill PROF_APPROVER_PRIV (never commit)
docker compose build
docker compose up -d
curl -sf localhost:8091/readyz && echo READY
open http://localhost:8091/console/
```

With public TLS edge:

```sh
PROF_DOMAIN=prof.example.com docker compose --profile edge up -d --build
```

Kubernetes: fill the `prof-approver` secret, then `kubectl apply -f deploy/k8s.yaml`.

## Key generation & rotation

```sh
python -c "from prof.identity import Approver; a=Approver.generate('user:alice'); print(a.pubkey_b64); print(a.export_private_b64())"
```

- Private key lives in a secret manager → mounted as `PROF_APPROVER_PRIV`. Gateway never logs it.
- Rotation: issue a new key, update the secret, rolling-restart. Outstanding permits bound to the old key fail verification (fail-closed) — re-approve in-flight work.
- Demo keys (`PROF_DEMO=1`) are ephemeral and must never be used in production.

## What to monitor

- `GET /metrics` — `allow` / `deny` counters, ledger size, nonce count.
- `GET /readyz` — ledger chain validity + store health (wire to load-balancer / k8s readiness).
- Alert on: `deny` spikes, `readyz != 200`, ledger growth stalls, restarts.

## Backup / restore

Ledger + nonces are the durable state (`/data`). `scripts/backup.sh` snapshots both; `scripts/restore.sh` restores and re-verifies the chain. Restoring a forked/old copy is detectable: nonces already spent will deny replays, and chain verify fails on tampering.

## Incident: suspected bypass

1. Freeze approvals (`PROF_REQUIRE_HUMAN=1` + restart, or stop edge).
2. `GET /v1/ledger` → export entries; `verify_chain` pinpoints tamper point.
3. Check infra: agent must have **no direct tool credentials** — every real path through the Gateway (network policy / security group audit).
4. Rotate approver key, re-approve, post-mortem with ledger evidence.

## Upgrade

Pull image → `docker compose up -d` (single replica, few seconds downtime in v0.1; HA is Beta roadmap). Ledger/nonces persist in the named volume.
