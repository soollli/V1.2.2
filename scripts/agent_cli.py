#!/usr/bin/env python3
"""Restricted CLI surface for Hermes/Agnes.

This wrapper is only meaningful when the harness exposes THIS command surface
instead of unrestricted shell access. It intentionally excludes operator-only
controls such as engine start, human approval creation and circuit reset.
"""
from __future__ import annotations
from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "hermes" / "TOOL_POLICY.json").read_text(encoding="utf-8"))
ALLOWED = set(POLICY["agent_allowed_commands"])


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/agent_cli.py <allowed-command> [args...]", file=sys.stderr)
        print("allowed=" + ",".join(sorted(ALLOWED)), file=sys.stderr)
        return 2
    command = sys.argv[1]
    if command not in ALLOWED:
        print(f"DENIED_BY_TOOL_POLICY: {command}", file=sys.stderr)
        return 13
    env = dict(os.environ)
    env["AI_QUANT_AGENT_CONTEXT"] = "1"
    proc = subprocess.run([sys.executable, str(ROOT / "run.py"), *sys.argv[1:]], cwd=ROOT, env=env)
    return int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
