from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import uuid
from typing import Any


def payload_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def write_receipt(root: Path, receipt: dict[str, Any]) -> tuple[str, Path]:
    now = datetime.now(timezone.utc)
    rid = receipt.get("receipt_id") or f"{now.strftime('%Y%m%dT%H%M%SZ')}_decision_{uuid.uuid4().hex[:8]}"
    obj = dict(receipt)
    obj["receipt_id"] = rid
    obj.setdefault("created_utc", now.isoformat())
    path = root / "logs" / "agent_receipts" / f"{rid}.json"
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)
    return rid, path
