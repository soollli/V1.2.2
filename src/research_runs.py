from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import uuid
from typing import Any

import pandas as pd

from .data_integrity import dataframe_fingerprint


def _json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _sha(obj: Any) -> str:
    return hashlib.sha256(_json_bytes(obj)).hexdigest()


def _atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def environment_snapshot() -> dict[str, Any]:
    packages = {}
    for name in ["pandas", "numpy", "requests", "PyYAML", "python-dotenv", "pytest", "pyqlib", "openbb-core"]:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "packages": packages,
    }


def dataset_manifest(data: pd.DataFrame | None) -> dict[str, Any]:
    if data is None:
        return {"present": False}
    manifest = {
        "present": True,
        "rows": int(len(data)),
        "columns": [str(x) for x in data.columns],
        "index_start": str(data.index[0]) if len(data) else None,
        "index_end": str(data.index[-1]) if len(data) else None,
        "fingerprint_sha256": dataframe_fingerprint(data),
    }
    attrs = getattr(data, "attrs", {}) or {}
    if attrs:
        manifest["source_attrs"] = {str(k): v for k, v in attrs.items()}
    return manifest


def archive_research_run(
    root: Path,
    *,
    kind: str,
    report: dict[str, Any],
    config: dict[str, Any],
    data: pd.DataFrame | None = None,
    latest_path: Path | None = None,
) -> tuple[str, Path]:
    """Write an immutable research bundle and optionally refresh a latest pointer."""
    now = datetime.now(timezone.utc)
    run_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}_{kind}_{uuid.uuid4().hex[:8]}"
    run_dir = Path(root) / "research" / "runs" / run_id
    if run_dir.exists():
        raise FileExistsError(run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)

    report = dict(report)
    report["run_id"] = run_id
    config_snapshot = json.loads(json.dumps(config, default=str))
    data_meta = dataset_manifest(data)
    env = environment_snapshot()
    manifest = {
        "run_id": run_id,
        "kind": kind,
        "created_utc": now.isoformat(),
        "project_version": (Path(root) / "VERSION").read_text(encoding="utf-8").strip() if (Path(root) / "VERSION").exists() else None,
        "config_sha256": _sha(config_snapshot),
        "data_sha256": data_meta.get("fingerprint_sha256"),
        "report_sha256": _sha(report),
        "reproducibility": {
            "immutable_run_directory": True,
            "environment_captured": True,
            "config_captured": True,
            "data_fingerprint_captured": True,
        },
    }
    _atomic_json(run_dir / "manifest.json", manifest)
    _atomic_json(run_dir / "config.json", config_snapshot)
    _atomic_json(run_dir / "data_manifest.json", data_meta)
    _atomic_json(run_dir / "environment.json", env)
    _atomic_json(run_dir / "report.json", report)
    if latest_path is not None:
        _atomic_json(latest_path, report)
    return run_id, run_dir
