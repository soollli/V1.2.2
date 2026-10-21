from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import itertools
import json
import math
from typing import Any

import numpy as np
import pandas as pd

from .backtest import BacktestResult, run_backtest


CRYPTO_PERIODS_PER_YEAR = {
    "1m": 365 * 24 * 60,
    "3m": 365 * 24 * 20,
    "5m": 365 * 24 * 12,
    "15m": 365 * 24 * 4,
    "30m": 365 * 24 * 2,
    "1h": 365 * 24,
    "2h": 365 * 12,
    "4h": 365 * 6,
    "6h": 365 * 4,
    "8h": 365 * 3,
    "12h": 365 * 2,
    "1d": 365,
    "3d": 365 / 3,
    "1w": 52,
    "1M": 12,
}


def _safe_div(a: float, b: float) -> float | None:
    if b is None or not np.isfinite(b) or abs(b) < 1e-12:
        return None
    return float(a / b)


def _iso(v: Any) -> str:
    try:
        return pd.Timestamp(v).isoformat()
    except Exception:
        return str(v)


def buy_hold_metrics(df: pd.DataFrame) -> dict:
    if len(df) < 2:
        return {"return_pct": 0.0}
    start = float(df.iloc[0]["close"])
    end = float(df.iloc[-1]["close"])
    return {
        "start_price": start,
        "end_price": end,
        "return_pct": (end / start - 1) * 100,
    }


def _drawdown_stats(equity: pd.Series) -> dict:
    if equity.empty:
        return {"max_drawdown_pct": 0.0, "max_underwater_bars": 0}
    peak = equity.cummax()
    dd = equity / peak - 1.0
    max_dd = float(dd.min())
    underwater = dd < 0
    longest = cur = 0
    for flag in underwater.tolist():
        cur = cur + 1 if flag else 0
        longest = max(longest, cur)
    return {
        "max_drawdown_pct": max_dd * 100,
        "max_underwater_bars": int(longest),
    }


def _trade_stats(round_trips: list[dict]) -> dict:
    rets = [float(t.get("return_pct", 0.0)) / 100 for t in round_trips]
    pnls = [float(t.get("net_pnl_quote", 0.0)) for t in round_trips]
    wins = [x for x in rets if x > 0]
    losses = [x for x in rets if x < 0]
    profit_sum = sum(x for x in pnls if x > 0)
    loss_sum = abs(sum(x for x in pnls if x < 0))
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = abs(float(np.mean(losses))) if losses else 0.0
    return {
        "round_trips": len(rets),
        "win_rate_pct": (len(wins) / len(rets) * 100) if rets else None,
        "avg_win_pct": avg_win * 100 if wins else None,
        "avg_loss_pct": avg_loss * 100 if losses else None,
        "win_loss_ratio": _safe_div(avg_win, avg_loss),
        "profit_factor": _safe_div(profit_sum, loss_sum),
    }


def performance_metrics(result: BacktestResult, df: pd.DataFrame, interval: str) -> dict:
    curve = result.equity_curve.copy()
    eval_df = df.copy()
    if curve.empty:
        eq = pd.Series([result.start_equity, result.end_equity], dtype=float)
    else:
        eq = curve["equity"].astype(float)
        # Align benchmark/sample window to the first bar where the strategy
        # equity curve actually exists (after indicator warm-up/start_index).
        first_curve_time = pd.to_datetime(curve.iloc[0].get("time"), utc=True, errors="coerce")
        if pd.notna(first_curve_time) and "close_time" in eval_df:
            ct = pd.to_datetime(eval_df["close_time"], utc=True, errors="coerce")
            aligned = eval_df.loc[ct >= first_curve_time].copy()
            if not aligned.empty:
                eval_df = aligned
    returns = eq.pct_change().dropna()
    ppy = float(CRYPTO_PERIODS_PER_YEAR.get(interval, 365.0))
    mean = float(returns.mean()) if len(returns) else 0.0
    std = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    downside = returns[returns < 0]
    downside_std = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    sharpe = _safe_div(mean * math.sqrt(ppy), std) if std else None
    sortino = _safe_div(mean * math.sqrt(ppy), downside_std) if downside_std else None

    t0 = pd.to_datetime(eval_df.iloc[0].get("close_time"), utc=True, errors="coerce")
    t1 = pd.to_datetime(eval_df.iloc[-1].get("close_time"), utc=True, errors="coerce")
    span_days = None
    annualized_return_pct = None
    if pd.notna(t0) and pd.notna(t1) and t1 > t0:
        span_days = (t1 - t0).total_seconds() / 86400.0
        # Avoid pretending a few hours of crypto bars is a reliable annual forecast.
        if span_days >= 7 and result.end_equity > 0:
            annualized_return_pct = ((result.end_equity / result.start_equity) ** (365.0 / span_days) - 1) * 100

    dd = _drawdown_stats(eq)
    calmar = None
    if annualized_return_pct is not None and dd["max_drawdown_pct"] < 0:
        calmar = annualized_return_pct / abs(dd["max_drawdown_pct"])

    benchmark = buy_hold_metrics(eval_df)
    trades = _trade_stats(result.round_trips)
    return {
        "sample": {
            "bars": int(len(eval_df)),
            "start": _iso(eval_df.iloc[0].get("close_time")),
            "end": _iso(eval_df.iloc[-1].get("close_time")),
            "span_days": span_days,
            "interval": interval,
            "annualization_basis": "crypto_24x7_365d",
        },
        "strategy": {
            "start_equity": result.start_equity,
            "end_equity": result.end_equity,
            "return_pct": result.return_pct,
            "annualized_return_pct": annualized_return_pct,
            "sharpe_like": sharpe,
            "sortino_like": sortino,
            "calmar_like": calmar,
            **dd,
            **trades,
            "orders": result.trades,
            "fees_paid_quote": result.fees_paid,
            "turnover_quote": result.turnover_quote,
            "fill_mode": result.fill_mode,
        },
        "benchmark_buy_hold": benchmark,
        "excess_return_pct": result.return_pct - benchmark["return_pct"],
    }



def research_timeseries(result: BacktestResult, interval: str, rolling_window: int = 60) -> dict:
    """Compact series for the web research desk. Uses only backtest information."""
    curve = result.equity_curve.copy()
    if curve.empty:
        return {"rows": [], "rolling_window_bars": rolling_window}
    curve = curve.dropna(subset=["time", "equity", "market_price"]).copy()
    if curve.empty:
        return {"rows": [], "rolling_window_bars": rolling_window}
    eq = curve["equity"].astype(float)
    px = curve["market_price"].astype(float)
    eq_norm = eq / float(eq.iloc[0]) * 100.0
    bh_norm = px / float(px.iloc[0]) * 100.0
    peak = eq.cummax()
    dd = (eq / peak - 1.0) * 100.0
    ret = eq.pct_change()
    ppy = float(CRYPTO_PERIODS_PER_YEAR.get(interval, 365.0))
    w = max(10, min(int(rolling_window), max(10, len(curve) // 2)))
    roll_mean = ret.rolling(w).mean()
    roll_std = ret.rolling(w).std(ddof=1)
    roll_sharpe = (roll_mean / roll_std) * math.sqrt(ppy)
    market_ret = px.pct_change()
    market_vol = market_ret.rolling(w).std(ddof=1) * math.sqrt(ppy) * 100.0
    median_vol = float(market_vol.dropna().median()) if market_vol.notna().any() else None
    rows = []
    for i, row in curve.reset_index(drop=True).iterrows():
        ts = pd.Timestamp(row["time"])
        rows.append({
            "time": ts.isoformat(),
            "ts": int(ts.timestamp() * 1000),
            "equity_index": float(eq_norm.iloc[i]),
            "benchmark_index": float(bh_norm.iloc[i]),
            "drawdown_pct": float(dd.iloc[i]),
            "rolling_sharpe": None if pd.isna(roll_sharpe.iloc[i]) else float(roll_sharpe.iloc[i]),
            "market_vol_annualized_pct": None if pd.isna(market_vol.iloc[i]) else float(market_vol.iloc[i]),
        })
    latest_sharpe = next((r["rolling_sharpe"] for r in reversed(rows) if r["rolling_sharpe"] is not None), None)
    latest_vol = next((r["market_vol_annualized_pct"] for r in reversed(rows) if r["market_vol_annualized_pct"] is not None), None)
    return {
        "rows": rows,
        "rolling_window_bars": w,
        "latest_rolling_sharpe": latest_sharpe,
        "latest_market_vol_annualized_pct": latest_vol,
        "median_market_vol_annualized_pct": median_vol,
        "market_regime": ("HIGH_VOL" if latest_vol is not None and median_vol is not None and latest_vol > median_vol else "NORMAL_VOL"),
    }

def strategy_report(df: pd.DataFrame, strategy_cfg: dict, risk_cfg: dict, initial_quote: float, interval: str) -> dict:
    result = run_backtest(df, strategy_cfg, risk_cfg, initial_quote)
    report = performance_metrics(result, df, interval)
    report["timeseries"] = research_timeseries(result, interval)
    report["strategy_config"] = dict(strategy_cfg)
    report["risk_config"] = dict(risk_cfg)
    report["generated_utc"] = datetime.now(timezone.utc).isoformat()
    return report


def parameter_scan(
    df: pd.DataFrame,
    strategy_cfg: dict,
    risk_cfg: dict,
    initial_quote: float,
    interval: str,
    train_fraction: float = 0.70,
    fast_values: list[int] | None = None,
    slow_values: list[int] | None = None,
) -> dict:
    fast_values = fast_values or [5, 9, 12, 15]
    slow_values = slow_values or [18, 21, 30, 50]
    split = max(100, min(len(df) - 50, int(len(df) * train_fraction)))
    if split <= 0 or split >= len(df):
        raise ValueError("not enough bars for train/test split")

    rows = []
    for fast, slow in itertools.product(fast_values, slow_values):
        if fast >= slow:
            continue
        cfg = dict(strategy_cfg)
        cfg["fast_ema"] = fast
        cfg["slow_ema"] = slow
        try:
            train_result = run_backtest(df.iloc[:split].copy(), cfg, risk_cfg, initial_quote)
            test_result = run_backtest(df.copy(), cfg, risk_cfg, initial_quote, start_index=split)
            train_m = performance_metrics(train_result, df.iloc[:split].copy(), interval)
            test_df = df.iloc[split:].copy()
            test_m = performance_metrics(test_result, test_df, interval)
            rows.append({
                "fast_ema": fast,
                "slow_ema": slow,
                "train_return_pct": train_m["strategy"]["return_pct"],
                "test_return_pct": test_m["strategy"]["return_pct"],
                "test_excess_return_pct": test_m["excess_return_pct"],
                "test_max_drawdown_pct": test_m["strategy"]["max_drawdown_pct"],
                "test_orders": test_m["strategy"]["orders"],
                "generalization_gap_pct": abs(train_m["strategy"]["return_pct"] - test_m["strategy"]["return_pct"]),
            })
        except ValueError:
            continue

    # OOS is the first sort key; smaller train-test gap is preferred on ties.
    rows.sort(key=lambda x: (x["test_return_pct"], -x["generalization_gap_pct"]), reverse=True)
    return {
        "split_index": split,
        "train_fraction": train_fraction,
        "rows": rows,
        "note": "Do not treat the top row as a magic optimum. Prefer broad parameter stability and OOS consistency.",
    }


def walk_forward(
    df: pd.DataFrame,
    strategy_cfg: dict,
    risk_cfg: dict,
    initial_quote: float,
    interval: str,
    folds: int = 3,
) -> dict:
    fast_values = [5, 9, 12, 15]
    slow_values = [18, 21, 30, 50]
    n = len(df)
    test_size = max(50, n // (folds + 2))
    first_train_end = n - folds * test_size
    if first_train_end < 120:
        raise ValueError("not enough bars for walk-forward")

    fold_rows = []
    for fold in range(folds):
        train_end = first_train_end + fold * test_size
        test_end = min(n, train_end + test_size)
        train_df = df.iloc[:train_end].copy()
        best = None
        for fast, slow in itertools.product(fast_values, slow_values):
            if fast >= slow:
                continue
            cfg = dict(strategy_cfg, fast_ema=fast, slow_ema=slow)
            try:
                r = run_backtest(train_df, cfg, risk_cfg, initial_quote)
            except ValueError:
                continue
            m = performance_metrics(r, train_df, interval)
            candidate = (m["strategy"]["return_pct"], -abs(m["strategy"]["max_drawdown_pct"]), fast, slow)
            if best is None or candidate > best[0]:
                best = (candidate, cfg, m)
        if best is None:
            continue
        cfg = best[1]
        test_full = df.iloc[:test_end].copy()
        r_test = run_backtest(test_full, cfg, risk_cfg, initial_quote, start_index=train_end)
        m_test = performance_metrics(r_test, df.iloc[train_end:test_end].copy(), interval)
        fold_rows.append({
            "fold": fold + 1,
            "train_bars": train_end,
            "test_start_index": train_end,
            "test_end_index": test_end,
            "selected_fast_ema": cfg["fast_ema"],
            "selected_slow_ema": cfg["slow_ema"],
            "train_return_pct": best[2]["strategy"]["return_pct"],
            "oos_return_pct": m_test["strategy"]["return_pct"],
            "oos_max_drawdown_pct": m_test["strategy"]["max_drawdown_pct"],
            "oos_orders": m_test["strategy"]["orders"],
        })

    params = [(x["selected_fast_ema"], x["selected_slow_ema"]) for x in fold_rows]
    stability = len(set(params)) / len(params) if params else None
    return {
        "folds": fold_rows,
        "parameter_variation_ratio": stability,
        "note": "Lower parameter variation can indicate stability, but must be read together with OOS performance.",
    }


def save_report(report: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def append_experiment_journal(path: Path, hypothesis: str, change: str, acceptance: str, result: str, conclusion: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "hypothesis": hypothesis,
        "change": change,
        "acceptance_criteria": acceptance,
        "result": result,
        "conclusion": conclusion,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path
