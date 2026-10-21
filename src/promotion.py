from __future__ import annotations
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
import json
import os
import uuid
from typing import Any

from .agent.ids import safe_identifier


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def load_research_run(root: Path, run_id: str) -> tuple[dict, dict]:
    run_id = safe_identifier(run_id, "research run id")
    d = root / "research" / "runs" / run_id
    if not d.is_dir():
        raise FileNotFoundError(f"research run not found: {run_id}")
    return _read_json(d / "manifest.json"), _read_json(d / "report.json")


def _positive_ratio(rows: list[dict], key: str) -> float | None:
    vals = [float(r[key]) for r in rows if r.get(key) is not None]
    return sum(v > 0 for v in vals) / len(vals) if vals else None


def evaluate_promotion(root: Path, cfg: dict[str, Any], run_ids: list[str]) -> dict[str, Any]:
    """Evaluate immutable research evidence and create a machine-readable gate result.

    This is intentionally conservative.  It does not execute anything and it does
    not infer missing evidence from LLM text.
    """
    pcfg = cfg.get("promotion_gate", {})
    ticket_ttl_hours = float(pcfg.get("ticket_ttl_hours", 24))
    minimum_folds = int(pcfg.get("minimum_walkforward_folds", 3))
    min_positive_oos = float(pcfg.get("minimum_positive_oos_ratio", 0.67))
    max_param_variation = float(pcfg.get("maximum_parameter_variation_ratio", 1.0))
    max_drawdown_abs = float(pcfg.get("maximum_drawdown_pct_abs", 25.0))
    min_excess = float(pcfg.get("minimum_excess_return_pct", 0.0))
    min_orders = int(pcfg.get("minimum_strategy_orders", 4))
    min_qlib_ic = float(pcfg.get("minimum_qlib_test_ic", 0.0))

    runs = []
    reasons: list[str] = []
    kinds: dict[str, tuple[dict, dict]] = {}
    for rid in run_ids:
        manifest, report = load_research_run(root, rid)
        kind = str(manifest.get("kind", "unknown"))
        runs.append({"run_id": rid, "kind": kind, "data_sha256": manifest.get("data_sha256"), "report_sha256": manifest.get("report_sha256")})
        kinds[kind] = (manifest, report)
        repro = manifest.get("reproducibility", {})
        if not all(repro.get(k) for k in ["immutable_run_directory", "environment_captured", "config_captured", "data_fingerprint_captured"]):
            reasons.append(f"{rid}: reproducibility manifest incomplete")

    if "strategy" not in kinds:
        reasons.append("missing strategy research run")
    else:
        report = kinds["strategy"][1]
        strat = report.get("strategy", {})
        dd = float(strat.get("max_drawdown_pct") or 0.0)
        excess = float(report.get("excess_return_pct") or 0.0)
        orders = int(strat.get("orders") or 0)
        if excess < min_excess:
            reasons.append(f"strategy excess return {excess:.3f}% < {min_excess:.3f}%")
        if abs(min(dd, 0.0)) > max_drawdown_abs:
            reasons.append(f"strategy max drawdown {dd:.3f}% exceeds {max_drawdown_abs:.3f}% limit")
        if orders < min_orders:
            reasons.append(f"strategy orders {orders} < {min_orders}")
        if strat.get("fill_mode") != "next_open":
            reasons.append("strategy evidence is not next_open execution")

    if "walkforward" not in kinds:
        reasons.append("missing walkforward research run")
    else:
        report = kinds["walkforward"][1]
        folds = report.get("folds", [])
        if len(folds) < minimum_folds:
            reasons.append(f"walkforward folds {len(folds)} < {minimum_folds}")
        ratio = _positive_ratio(folds, "oos_return_pct")
        if ratio is None or ratio < min_positive_oos:
            reasons.append(f"walkforward positive OOS ratio {ratio} < {min_positive_oos}")
        variation = report.get("parameter_variation_ratio")
        if variation is None or float(variation) > max_param_variation:
            reasons.append(f"parameter variation ratio {variation} > {max_param_variation}")

    if "qlib_ml" in kinds:
        report = kinds["qlib_ml"][1]
        ic = report.get("test_metrics", {}).get("ic_mean")
        if ic is None or float(ic) <= min_qlib_ic:
            reasons.append(f"Qlib test IC {ic} <= {min_qlib_ic}")

    passed = not reasons
    now = datetime.now(timezone.utc)
    ticket_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}_promotion_{uuid.uuid4().hex[:8]}"
    ticket = {
        "ticket_id": ticket_id,
        "created_utc": now.isoformat(),
        "expires_utc": (now + timedelta(hours=ticket_ttl_hours)).isoformat(),
        "status": "PASSED" if passed else "REJECTED",
        "passed": passed,
        "run_ids": run_ids,
        "evidence": runs,
        "thresholds": {
            "ticket_ttl_hours": ticket_ttl_hours,
            "minimum_walkforward_folds": minimum_folds,
            "minimum_positive_oos_ratio": min_positive_oos,
            "maximum_parameter_variation_ratio": max_param_variation,
            "maximum_drawdown_pct_abs": max_drawdown_abs,
            "minimum_excess_return_pct": min_excess,
            "minimum_strategy_orders": min_orders,
            "minimum_qlib_test_ic": min_qlib_ic,
        },
        "reasons": reasons,
        "evidence_sha256": hashlib.sha256(json.dumps(runs, sort_keys=True, default=str).encode()).hexdigest(),
        "live_money_authority": False,
    }
    _atomic_json(root / "research" / "promotions" / f"{ticket_id}.json", ticket)
    return ticket


def load_promotion_ticket(root: Path, ticket_id: str) -> dict[str, Any]:
    ticket_id = safe_identifier(ticket_id, "promotion ticket id")
    path = root / "research" / "promotions" / f"{ticket_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"promotion ticket not found: {ticket_id}")
    return _read_json(path)
