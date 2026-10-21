from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import csv
import json
import os

from .config import Settings
from .state import PortfolioState
from .core.registry import AdapterRegistry
from .agent import ActionGateway


def mode_path(settings: Settings, key: str, mode: str) -> Path:
    raw = str(settings.storage[key])
    return settings.root / raw.format(mode=mode)


def _tail(path: Path, n: int = 20) -> list[str]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-n:]
    except Exception:
        return []


def _recent_trades(path: Path, n: int = 20) -> list[dict]:
    if not path.exists():
        return []
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        return rows[-n:]
    except Exception:
        return []




def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}



def _execution_stats(path: Path, n: int = 200) -> dict:
    rows = _recent_trades(path, n)
    vals, fees = [], 0.0
    for r in rows:
        try:
            if r.get("slippage_bps_realized") not in (None, ""):
                vals.append(float(r["slippage_bps_realized"]))
            fees += float(r.get("fee_quote") or 0.0)
        except Exception:
            pass
    return {
        "fills": len(rows),
        "fills_with_slippage_measurement": len(vals),
        "avg_slippage_bps": (sum(vals) / len(vals)) if vals else None,
        "max_abs_slippage_bps": max((abs(x) for x in vals), default=None),
        "fees_quote": fees,
    }


def _journal_tail(path: Path, n: int = 12) -> list[dict]:
    if not path.exists(): return []
    out=[]
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]:
            try: out.append(json.loads(line))
            except Exception: pass
    except Exception: pass
    return out

def _pid_status(lock_path: Path) -> tuple[bool, int | None]:
    if not lock_path.exists():
        return False, None
    try:
        pid = int(lock_path.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
        return True, pid
    except Exception:
        return False, None





def _latest_json_in_dir(path: Path) -> dict:
    if not path.exists():
        return {}
    files = sorted(path.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
    return _read_json(files[0]) if files else {}

def build_research_bundle(settings: Settings) -> dict:
    research_dir = settings.root / settings.raw.get("research", {}).get("output_dir", "research/results")
    journal_path = settings.root / settings.raw.get("research", {}).get("journal_file", "research/experiment_journal.jsonl")
    return {
        "latest_strategy_report": _read_json(research_dir / "latest_strategy_report.json"),
        "latest_parameter_scan": _read_json(research_dir / "latest_parameter_scan.json"),
        "latest_walkforward": _read_json(research_dir / "latest_walkforward.json"),
        "latest_factor_report": _read_json(research_dir / "latest_factor_report.json"),
        "latest_capm_report": _read_json(research_dir / "latest_capm_report.json"),
        "latest_portfolio_report": _read_json(research_dir / "latest_portfolio_report.json"),
        "latest_theories_report": _read_json(research_dir / "latest_theories_report.json"),
        "latest_qlib_ml_report": _read_json(research_dir / "latest_qlib_ml_report.json"),
        "latest_promotion_ticket": _latest_json_in_dir(settings.root / "research" / "promotions"),
        "journal": _journal_tail(journal_path),
    }

def build_status(settings: Settings, mode: str = "paper") -> dict:
    state_path = mode_path(settings, "state_file", mode)
    trades_path = mode_path(settings, "trades_file", mode)
    events_path = mode_path(settings, "events_file", mode)
    lock_path = settings.root / "data" / f"engine_{mode}.pid"

    state = PortfolioState.load(state_path, settings.broker["initial_quote_balance"])
    running, pid = _pid_status(lock_path)
    research_dir = settings.root / settings.raw.get("research", {}).get("output_dir", "research/results")
    latest_research = _read_json(research_dir / "latest_strategy_report.json")
    latest_summary = dict(latest_research)
    latest_summary.pop("timeseries", None)
    last_price = float(state.last_price or 0.0)
    unrealized = (last_price - state.avg_entry) * state.base_qty if state.base_qty > 0 and last_price > 0 else 0.0
    marked_equity = state.quote_balance + state.base_qty * last_price if mode == "paper" else None

    return {
        "project": settings.raw.get("project", {}).get("name", "quant-mvp"),
        "mode": mode,
        "engine_running": running,
        "engine_pid": pid,
        "symbol": settings.market["symbol"],
        "interval": settings.market["interval"],
        "strategy": settings.strategy.get("name", "unknown"),
        "state": {
            **state.to_dict(),
            "unrealized_pnl_mark": unrealized,
            "marked_equity": marked_equity,
        },
        "recent_trades": _recent_trades(trades_path, 20),
        "recent_events": _tail(events_path, 30),
        "research": {
            "latest_strategy_report": latest_summary,
            "available": bool(latest_research),
        },
        "execution": _execution_stats(trades_path),
        "monitoring": settings.raw.get("monitoring", {}),
        "adapters": AdapterRegistry(settings).capabilities()["core"],
        "agent_safety": ActionGateway(settings).capabilities(),
        "paths": {
            "state": str(state_path),
            "trades": str(trades_path),
            "events": str(events_path),
            "lock": str(lock_path),
        },
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def print_status_json(settings: Settings, mode: str = "paper"):
    print(json.dumps(build_status(settings, mode), ensure_ascii=False, indent=2))
