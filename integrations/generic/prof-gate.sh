#!/bin/sh
# Generic pre-tool gate for any agent with shell hooks (incl. Dots and friends).
# Env in:  PROF_ACTION, PROF_RESOURCE, PROF_ARGS (JSON object string)
#           PROF_STRICT=1 -> block when mapping/vars are missing
# Out: exit 0 allow / exit 2 block (Claude-hook compatible).
set -eu
if [ -z "${PROF_ACTION:-}" ] || [ -z "${PROF_RESOURCE:-}" ]; then
  if [ "${PROF_STRICT:-0}" = "1" ]; then
    echo "PROF blocked: PROF_ACTION/PROF_RESOURCE not set" >&2; exit 2
  fi
  exit 0
fi
if command -v prof >/dev/null 2>&1; then PROF_BIN="prof"; else PROF_BIN="python3 -m prof"; fi
# shellcheck disable=SC2086
exec $PROF_BIN decide --action "$PROF_ACTION" --resource "$PROF_RESOURCE" \
  --args "${PROF_ARGS:-{}}" --claude-hook
