from __future__ import annotations
from pathlib import Path
from typing import Any
import json
import pandas as pd

from ...market import BinanceMarketData
from ...core.contracts import AdapterInfo
from ...core.schemas import normalize_klines
from ...data_integrity import dataframe_fingerprint, validate_klines


class BinanceDataAdapter:
    info = AdapterInfo(
        kind="data",
        name="binance",
        provider="Binance REST",
        description="Native Binance Spot OHLCV/ticker with paginated history and integrity checks",
        live_money=False,
    )

    def __init__(self, use_testnet: bool = False, timeout: int = 10, cache_dir: Path | None = None):
        self.client = BinanceMarketData(use_testnet=use_testnet, timeout=timeout)
        self.use_testnet = use_testnet
        self.cache_dir = Path(cache_dir) if cache_dir else None

    def klines(self, symbol: str, interval: str, limit: int = 250):
        return normalize_klines(self.client.klines(symbol, interval, limit))

    def _cache_paths(self, symbol: str, interval: str) -> tuple[Path | None, Path | None]:
        if self.cache_dir is None:
            return None, None
        base = self.cache_dir / f"{symbol.upper()}_{interval}"
        return base.with_suffix(".csv.gz"), base.with_suffix(".meta.json")

    @staticmethod
    def _merge(*frames: pd.DataFrame) -> pd.DataFrame:
        valid = [x for x in frames if x is not None and not x.empty]
        if not valid:
            return pd.DataFrame()
        out = pd.concat(valid, ignore_index=True)
        out = normalize_klines(out)
        out = out.drop_duplicates(subset=["open_time"], keep="last").sort_values("open_time").reset_index(drop=True)
        return out

    def _load_cache(self, symbol: str, interval: str) -> pd.DataFrame:
        path, _ = self._cache_paths(symbol, interval)
        if path is None or not path.exists():
            return pd.DataFrame()
        try:
            df = pd.read_csv(path, compression="gzip")
            return normalize_klines(df)
        except Exception:
            return pd.DataFrame()

    def _save_cache(self, symbol: str, interval: str, df: pd.DataFrame, integrity: dict[str, Any]) -> None:
        path, meta = self._cache_paths(symbol, interval)
        if path is None or meta is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        df.to_csv(tmp, index=False, compression="gzip", date_format="%Y-%m-%dT%H:%M:%S.%f%z")
        tmp.replace(path)
        payload = {
            "symbol": symbol.upper(),
            "interval": interval,
            "rows": int(len(df)),
            "integrity": integrity,
            "fingerprint": dataframe_fingerprint(df, ["open_time", "open", "high", "low", "close", "volume", "close_time"]),
        }
        meta.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def history(
        self,
        symbol: str,
        interval: str,
        bars: int,
        *,
        closed_only: bool = True,
        use_cache: bool = True,
        strict: bool = True,
    ) -> pd.DataFrame:
        """Return the latest N bars without silently truncating at Binance's 1000-row page limit."""
        bars = int(bars)
        if bars <= 0:
            raise ValueError("bars must be positive")

        cached = self._load_cache(symbol, interval) if use_cache else pd.DataFrame()
        # Always refresh the newest page so the cache does not silently go stale.
        recent = normalize_klines(self.client.klines(symbol, interval, min(1000, max(2, bars))))
        merged = self._merge(cached, recent)

        if closed_only and not merged.empty:
            now = pd.Timestamp.now(tz="UTC")
            merged = merged[pd.to_datetime(merged["close_time"], utc=True) <= now].copy()

        # Walk backwards using endTime; official Spot REST max page size is 1000.
        while len(merged) < bars:
            if merged.empty:
                end_ms = None
            else:
                oldest = pd.Timestamp(merged.iloc[0]["open_time"])
                end_ms = int(oldest.timestamp() * 1000) - 1
            need = min(1000, bars - len(merged))
            batch = normalize_klines(self.client.klines(symbol, interval, max(2, need), end_time=end_ms))
            if closed_only and not batch.empty:
                now = pd.Timestamp.now(tz="UTC")
                batch = batch[pd.to_datetime(batch["close_time"], utc=True) <= now].copy()
            before = len(merged)
            merged = self._merge(batch, merged)
            if batch.empty or len(merged) == before:
                break

        if len(merged) < bars:
            raise ValueError(f"requested {bars} closed bars but Binance/cache returned only {len(merged)}")
        result = merged.tail(bars).reset_index(drop=True)
        integrity = validate_klines(result, interval, strict=strict).to_dict()
        if use_cache:
            # Keep all fetched history, not only the requested tail.
            full_integrity = validate_klines(merged, interval, strict=strict).to_dict()
            self._save_cache(symbol, interval, merged, full_integrity)
        result.attrs["integrity"] = integrity
        result.attrs["fingerprint"] = dataframe_fingerprint(result, ["open_time", "open", "high", "low", "close", "volume", "close_time"])
        result.attrs["requested_bars"] = bars
        result.attrs["source"] = "binance_spot_rest"
        return result

    def price(self, symbol: str) -> float:
        return self.client.price(symbol)

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "adapter": self.info.name,
            "testnet": self.use_testnet,
            "network_checked": False,
            "history_pagination": True,
            "history_cache": str(self.cache_dir) if self.cache_dir else None,
        }
