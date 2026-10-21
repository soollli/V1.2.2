from __future__ import annotations
from dataclasses import dataclass, asdict
import hashlib
import io
from typing import Any
import pandas as pd


_INTERVAL_SECONDS = {
    "1s": 1,
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800, "12h": 43200,
    "1d": 86400, "3d": 259200, "1w": 604800,
}


class DataIntegrityError(ValueError):
    pass


@dataclass
class KlineIntegrityReport:
    ok: bool
    rows: int
    duplicate_open_times: int
    non_monotonic: bool
    gaps: int
    expected_interval_seconds: int | None
    start: str | None
    end: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def interval_seconds(interval: str) -> int | None:
    return _INTERVAL_SECONDS.get(str(interval))


def validate_klines(df: pd.DataFrame, interval: str, *, strict: bool = True) -> KlineIntegrityReport:
    if df is None or df.empty:
        raise DataIntegrityError("kline dataframe is empty")
    if "open_time" not in df or "close_time" not in df:
        raise DataIntegrityError("kline dataframe lacks open_time/close_time")
    t = pd.to_datetime(df["open_time"], utc=True, errors="coerce")
    if t.isna().any():
        raise DataIntegrityError("kline dataframe contains invalid open_time")
    duplicates = int(t.duplicated().sum())
    non_monotonic = not bool(t.is_monotonic_increasing)
    step = interval_seconds(interval)
    gaps = 0
    if step is not None and len(t) > 1:
        delta = t.diff().dropna().dt.total_seconds()
        gaps = int((delta > step * 1.5).sum())
    report = KlineIntegrityReport(
        ok=(duplicates == 0 and not non_monotonic and gaps == 0),
        rows=int(len(df)),
        duplicate_open_times=duplicates,
        non_monotonic=non_monotonic,
        gaps=gaps,
        expected_interval_seconds=step,
        start=t.iloc[0].isoformat() if len(t) else None,
        end=t.iloc[-1].isoformat() if len(t) else None,
    )
    if strict and not report.ok:
        raise DataIntegrityError(f"kline integrity failed: {report.to_dict()}")
    return report


def dataframe_fingerprint(df: pd.DataFrame, columns: list[str] | None = None) -> str:
    """Stable SHA256 fingerprint for a research dataset."""
    x = df.copy()
    if columns:
        x = x[[c for c in columns if c in x.columns]]
    # CSV is slower than Arrow hashing but dependency-free and deterministic for
    # the modest personal-research datasets this terminal targets.
    buf = io.StringIO()
    x.to_csv(buf, index=True, date_format="%Y-%m-%dT%H:%M:%S.%f%z", float_format="%.12g")
    return hashlib.sha256(buf.getvalue().encode("utf-8")).hexdigest()
