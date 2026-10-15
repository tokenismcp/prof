#!/usr/bin/env python3
"""Claude Code PreToolUse hook: gate tool calls through PROF policy tiers.

Reads the hook JSON from stdin ({tool_name, tool_input, ...}), maps it to a
PROF action/resource, and runs `prof decide --claude-hook`:
  exit 0 -> allow (low/medium tier, logged to the PROF ledger)
  exit 2 -> block (high tier or policy deny; message goes back to Claude)

Unmapped tools pass through unless PROF_STRICT=1 (then they block).

Install: copy .mcp.json + settings snippet from this folder (see ../docs/AGENTS.md).
Requires `prof` on PATH (pip install -e /path/to/prof).
"""

import json
import os
import subprocess
import sys


def prof_cmd():
    return [sys.executable, "-m", "prof"]


def decide(action, resource, args):
    r = subprocess.run(
        prof_cmd() + ["decide", "--action", action, "--resource", resource,
                      "--args", json.dumps(args), "--claude-hook"],
        capture_output=True, text=True)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


def main():
    try:
        hook = json.load(sys.stdin)
    except Exception:
        return 0  # unreadable input: don't break the agent
    tool = hook.get("tool_name", "")
    inp = hook.get("tool_input", {}) or {}
    strict = os.environ.get("PROF_STRICT", "0") == "1"

    mapping = None
    if tool in ("Write", "Edit", "NotebookEdit"):
        mapping = ("file.write", f"file:{inp.get('file_path', 'unknown')}", inp)
    elif tool == "Bash":
        mapping = ("tool.call", "tool:shell", {"cmd": inp.get("command", "")[:500]})
    elif tool in ("WebFetch", "WebSearch"):
        mapping = ("tool.call", "tool:web.fetch", {"url": inp.get("url", inp.get("query", ""))[:300]})
    elif tool in ("Read", "Glob", "Grep", "LSP"):
        mapping = ("tool.call", "tool:code.read", {"tool": tool})

    if mapping is None:
        if strict:
            sys.stderr.write(f"PROF blocked unmapped tool '{tool}' (PROF_STRICT=1)\n")
            return 2
        return 0
    return decide(*mapping)


if __name__ == "__main__":
    sys.exit(main())
