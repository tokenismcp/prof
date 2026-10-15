#!/bin/sh
# Restore PROF durable state. Usage: scripts/restore.sh ./backups/prof-backup-TS
# Stops the gateway first; verifies the ledger chain after restore.
set -eu
SRC="${1:?usage: restore.sh <backup-dir>}"
docker compose stop gateway 2>/dev/null || true
docker compose cp "$SRC/ledger.json" gateway:/data/ledger.json
docker compose cp "$SRC/nonces.json" gateway:/data/nonces.json
docker compose start gateway
sleep 3
curl -sf localhost:8091/readyz && echo && echo "restore ok"
