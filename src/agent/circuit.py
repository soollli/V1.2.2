from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json
import os
from typing import Any


def _path(root: Path) -> Path:
    return root / "data" / "agent_circuit_breaker.json"


def circuit_status(root: Path) -> dict[str, Any]:
    path = _path(root)
    if not path.exists():
        return {
            "state": "NORMAL",
            "halted": False,
            "reason": "default_fail_safe_state",
            "updated_utc": None,
            "updated_by": None,
        }
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        state = str(obj.get("state", "HALTED")).upper()
        obj["state"] = state
        obj["halted"] = state != "NORMAL"
        return obj
    except Exception as exc:
        # Corrupt safety state must fail closed.
        return {
            "state": "HALTED",
            "halted": True,
            "reason": f"circuit_state_unreadable:{type(exc).__name__}",
            "updated_utc": None,
            "updated_by": "system_fail_closed",
        }


def set_circuit(root: Path, *, halted: bool, reason: str, updated_by: str = "human_operator") -> dict[str, Any]:
    obj = {
        "state": "HALTED" if halted else "NORMAL",
        "halted": bool(halted),
        "reason": str(reason or ("manual_halt" if halted else "manual_reset")),
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "updated_by": updated_by,
    }
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return obj
