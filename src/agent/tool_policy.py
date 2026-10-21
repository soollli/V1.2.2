from __future__ import annotations
from pathlib import Path
import json


def load_tool_policy(root: Path) -> dict:
    path = root / "hermes" / "TOOL_POLICY.json"
    return json.loads(path.read_text(encoding="utf-8"))


def is_agent_command_allowed(root: Path, command: str) -> bool:
    p = load_tool_policy(root)
    return command in set(p.get("agent_allowed_commands", []))


def is_operator_only(root: Path, command: str) -> bool:
    p = load_tool_policy(root)
    return command in set(p.get("operator_only_commands", []))
