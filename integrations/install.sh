#!/bin/sh
# PROF installer — guarantees a working `prof` binary on old and new pip.
#
#   sh integrations/install.sh
#
# Steps: install package (editable when pip supports it) -> locate the
# `prof` binary -> verify `prof demo` -> print ready-to-paste MCP JSON
# with an ABSOLUTE command path (GUI-launched agents don't inherit $PATH).
set -eu
PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || { echo "error: python3 not found" >&2; exit 1; }
cd "$(dirname "$0")/.."

if "$PY" -m pip install -e . >/dev/null 2>&1; then
  echo "installed (editable)"
else
  echo "editable install unsupported by this pip; installing snapshot instead"
  "$PY" -m pip install --user . || "$PY" -m pip install .
fi

USERBIN="$("$PY" -m site --user-base 2>/dev/null)/bin"
PROF_BIN=""
for cand in "$(command -v prof 2>/dev/null || true)" "$USERBIN/prof" "$HOME/.local/bin/prof"; do
  if [ -x "${cand:-x}" ]; then PROF_BIN="$cand"; break; fi
done
if [ -z "$PROF_BIN" ]; then
  echo "error: 'prof' binary not found after install." >&2
  echo "Add your python bin dir to PATH, e.g.:" >&2
  echo "  export PATH=\"\$PATH:$USERBIN\"" >&2
  exit 1
fi
echo "prof binary: $PROF_BIN"
if ! "$PROF_BIN" demo >/dev/null 2>&1; then
  echo "warning: 'prof demo' did not pass; run '$PROF_BIN demo' for details" >&2
else
  echo "verified: prof demo PASS"
fi
if ! command -v prof >/dev/null 2>&1; then
  echo "note: 'prof' is not on PATH. Add this to your shell rc:" >&2
  echo "  export PATH=\"\$PATH:$(dirname "$PROF_BIN")\"" >&2
fi
echo
echo "MCP JSON for your agent (absolute path, paste into MCP config):"
echo "{ \"mcpServers\": { \"prof\": { \"command\": \"$PROF_BIN\", \"args\": [\"mcp\"] } } }"
