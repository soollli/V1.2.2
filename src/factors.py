from __future__ import annotations
from datetime import datetime, timezone
from typing import Iterable
import math
import numpy as np
import pandas as pd


def _safe_float(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except Exception:
        return None


def factor_matrices(closes: pd.DataFrame, momentum_period: int = 20, vol_period: int = 20, reversal_period: int = 5) -> dict[str, pd.DataFrame]:
    """Build cross-sectional factor matrices. Rows=time, columns=symbols."""
    rets = closes.pct_change()
    momentum = closes.pct_change(momentum_period)
    vol = rets.rolling(vol_period).std(ddof=1)
    ram = momentum / vol.replace(0, np.nan)
    reversal = -closes.pct_change(reversal_period)
    return {"momentum": momentum, "ram": ram, "volatility": vol, "reversal": reversal}


def forward_returns(closes: pd.DataFrame, horizon: int) -> pd.DataFrame:
    return closes.pct_change(horizon).shift(-horizon)


def compute_ic_series(factor_df: pd.DataFrame, fwd_df: pd.DataFrame, min_assets: int = 5) -> pd.Series:
    rows = []
    idx = factor_df.index.intersection(fwd_df.index)
    cols = factor_df.columns.intersection(fwd_df.columns)
    for t in idx:
        a = factor_df.loc[t, cols]
        b = fwd_df.loc[t, cols]
        ok = a.notna() & b.notna()
        if int(ok.sum()) < int(min_assets):
            continue
        ic = a[ok].corr(b[ok], method="spearman")
        if pd.notna(ic):
            rows.append((t, float(ic)))
    return pd.Series(dict(rows), dtype=float).sort_index()


def compute_grouped_ic(factor_df: pd.DataFrame, fwd_df: pd.DataFrame, vol_df: pd.DataFrame, min_assets: int = 3) -> dict[str, pd.Series]:
    high, low = [], []
    idx = factor_df.index.intersection(fwd_df.index).intersection(vol_df.index)
    cols = factor_df.columns.intersection(fwd_df.columns).intersection(vol_df.columns)
    for t in idx:
        fac, fwd, vol = factor_df.loc[t, cols], fwd_df.loc[t, cols], vol_df.loc[t, cols]
        ok = fac.notna() & fwd.notna() & vol.notna()
        if int(ok.sum()) < min_assets * 2:
            continue
        med = float(vol[ok].median())
        for name, mask, bucket in [
            ("high", ok & (vol >= med), high),
            ("low", ok & (vol < med), low),
        ]:
            if int(mask.sum()) < min_assets:
                continue
            ic = fac[mask].corr(fwd[mask], method="spearman")
            if pd.notna(ic): bucket.append((t, float(ic)))
    return {
        "high_vol": pd.Series(dict(high), dtype=float).sort_index(),
        "low_vol": pd.Series(dict(low), dtype=float).sort_index(),
    }


def _ic_summary(s: pd.Series) -> dict:
    s = s.dropna()
    mean = float(s.mean()) if len(s) else None
    std = float(s.std(ddof=1)) if len(s) > 1 else None
    icir = (mean / std) if mean is not None and std not in (None, 0) else None
    return {
        "observations": int(len(s)),
        "ic_mean": mean,
        "ic_std": std,
        "icir": icir,
        "ic_positive_pct": float((s > 0).mean() * 100) if len(s) else None,
    }


def analyze_factor_matrix(closes: pd.DataFrame, momentum_period: int = 20, vol_period: int = 20,
                          reversal_period: int = 5, forward_windows: Iterable[int] = (5, 10, 20),
                          min_assets: int = 5, group_min_assets: int = 4) -> dict:
    factors = factor_matrices(closes, momentum_period, vol_period, reversal_period)
    rows = []
    ic_series_payload = {}
    grouped_payload = {}
    for horizon in forward_windows:
        fwd = forward_returns(closes, int(horizon))
        for factor_name, mat in factors.items():
            ic = compute_ic_series(mat, fwd, min_assets=min_assets)
            summary = _ic_summary(ic)
            row = {"factor": factor_name, "forward_bars": int(horizon), **summary}
            rows.append(row)
            key = f"{factor_name}:{horizon}"
            ic_series_payload[key] = [{"time": pd.Timestamp(t).isoformat(), "ic": float(v)} for t, v in ic.items()]
            if factor_name in {"momentum", "ram"}:
                grouped = compute_grouped_ic(mat, fwd, factors["volatility"], min_assets=max(4, int(group_min_assets)))
                grouped_payload[key] = {name: _ic_summary(series) for name, series in grouped.items()}
    rows.sort(key=lambda r: abs(r["ic_mean"] or 0), reverse=True)
    return {
        "universe": list(closes.columns),
        "bars": int(len(closes)),
        "momentum_period": momentum_period,
        "vol_period": vol_period,
        "reversal_period": reversal_period,
        "forward_windows": list(map(int, forward_windows)),
        "rows": rows,
        "grouped_ic": grouped_payload,
        "ic_series": ic_series_payload,
        "group_min_assets": max(4, int(group_min_assets)),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "discipline_note": "Cross-sectional Spearman IC. Small universes are exploratory; grouped IC is withheld unless each subgroup has enough assets.",
    }


def fetch_close_matrix(market, universe: list[str], interval: str, limit: int = 1000) -> pd.DataFrame:
    series = {}
    fingerprints = {}
    for symbol in universe:
        if hasattr(market, "history"):
            df = market.history(symbol, interval, int(limit), closed_only=True, use_cache=True, strict=True)
        else:
            df = market.klines(symbol, interval, int(limit))
            if len(df) > 1:
                df = df.iloc[:-1].copy()
        if df.empty:
            continue
        t = pd.to_datetime(df["close_time"], utc=True, errors="coerce")
        s = pd.Series(df["close"].astype(float).to_numpy(), index=t, name=symbol)
        s = s[~s.index.duplicated(keep="last")]
        series[symbol] = s
        if getattr(df, "attrs", None):
            fingerprints[symbol] = df.attrs.get("fingerprint")
    if not series:
        return pd.DataFrame()
    out = pd.concat(series.values(), axis=1, join="inner").dropna(how="any")
    out.attrs["source_fingerprints"] = fingerprints
    out.attrs["requested_bars"] = int(limit)
    return out
