#!/bin/sh
# Backup PROF durable state (ledger + nonces). Usage: scripts/backup.sh ./backups
set -eu
DEST="${1:-./backups}/prof-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DEST"
docker compose cp gateway:/data/ledger.json "$DEST/ledger.json" 2>/dev/null \
  || cp ./data/ledger.json "$DEST/ledger.json" 2>/dev/null \
  || echo "ledger: nothing to back up yet"
docker compose cp gateway:/data/nonces.json "$DEST/nonces.json" 2>/dev/null \
  || cp ./data/nonces.json "$DEST/nonces.json" 2>/dev/null \
  || echo "nonces: nothing to back up yet"
echo "backup -> $DEST"
