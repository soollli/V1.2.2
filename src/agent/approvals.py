from __future__ import annotations
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import os
import secrets
from typing import Any

from .receipts import payload_hash
from .ids import safe_identifier


def _atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def create_human_approval(
    root: Path,
    *,
    skill: str,
    mode: str,
    payload: dict[str, Any],
    promotion_ticket: str | None,
    ttl_minutes: float = 10.0,
) -> dict[str, Any]:
    """Create a short-lived, one-time human approval receipt.

    This function must NOT be exposed as an agent skill.  It represents the
    out-of-band human confirmation boundary.
    """
    now = datetime.now(timezone.utc)
    approval_id = f"approve_{now.strftime('%Y%m%dT%H%M%SZ')}_{secrets.token_hex(8)}"
    obj = {
        "approval_id": approval_id,
        "created_utc": now.isoformat(),
        "expires_utc": (now + timedelta(minutes=float(ttl_minutes))).isoformat(),
        "skill": skill,
        "mode": mode,
        "promotion_ticket": promotion_ticket,
        "payload_sha256": payload_hash(payload),
        "one_time": True,
        "created_by": "human_out_of_band",
    }
    _atomic_json(root / "data" / "human_approvals" / f"{approval_id}.json", obj)
    return obj


def validate_human_approval(
    root: Path,
    *,
    approval_id: str,
    skill: str,
    mode: str,
    payload: dict[str, Any],
    promotion_ticket: str | None,
) -> tuple[bool, str, dict[str, Any] | None]:
    approval_id = safe_identifier(approval_id, "human approval id")
    path = root / "data" / "human_approvals" / f"{approval_id}.json"
    if not path.exists():
        return False, "human approval receipt not found", None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"human approval receipt unreadable: {type(exc).__name__}", None
    if obj.get("skill") != skill or obj.get("mode") != mode:
        return False, "human approval does not match skill/mode", obj
    if obj.get("promotion_ticket") != promotion_ticket:
        return False, "human approval does not match promotion ticket", obj
    if obj.get("payload_sha256") != payload_hash(payload):
        return False, "human approval does not match action payload", obj
    try:
        expiry = datetime.fromisoformat(str(obj.get("expires_utc")).replace("Z", "+00:00"))
        if datetime.now(timezone.utc) >= expiry:
            return False, "human approval receipt expired", obj
    except Exception:
        return False, "human approval receipt has invalid expiry", obj
    consumed = root / "data" / "human_approval_consumed" / f"{approval_id}.json"
    if consumed.exists():
        return False, "human approval receipt already consumed", obj
    return True, "ok", obj


def consume_human_approval(root: Path, approval_id: str, decision_receipt_id: str | None) -> Path:
    approval_id = safe_identifier(approval_id, "human approval id")
    path = root / "data" / "human_approval_consumed" / f"{approval_id}.json"
    if path.exists():
        raise FileExistsError(f"approval already consumed: {approval_id}")
    obj = {
        "approval_id": approval_id,
        "consumed_utc": datetime.now(timezone.utc).isoformat(),
        "decision_receipt_id": decision_receipt_id,
    }
    _atomic_json(path, obj)
    return path
