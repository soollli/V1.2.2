from __future__ import annotations
import pandas as pd

KLINE_REQUIRED = ("open_time", "open", "high", "low", "close", "volume", "close_time")


def normalize_klines(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize every data adapter into the terminal's canonical OHLCV schema."""
    out = df.copy()
    missing = [c for c in KLINE_REQUIRED if c not in out.columns]
    if missing:
        raise ValueError(f"market data missing canonical columns: {missing}")
    for c in ("open", "high", "low", "close", "volume"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    for c in ("open_time", "close_time"):
        out[c] = pd.to_datetime(out[c], utc=True, errors="coerce")
    out = out.dropna(subset=list(KLINE_REQUIRED)).sort_values("open_time").reset_index(drop=True)
    return out
