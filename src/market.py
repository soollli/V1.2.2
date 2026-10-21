from __future__ import annotations
from pathlib import Path
import os
import requests
import pandas as pd

PROD_BASE = "https://api.binance.com"
TESTNET_BASE = "https://testnet.binance.vision"
# Read-only public data mirror, usable when api.binance.com is geo-blocked
# (e.g. HTTP 451). Market data only; trading endpoints stay on the real hosts.
BINANCE_BASE_URL_ENV = "AI_QUANT_BINANCE_BASE_URL"


class BinanceMarketData:
    def __init__(self, use_testnet: bool = False, timeout: int = 10):
        override = os.environ.get(BINANCE_BASE_URL_ENV, "").strip().rstrip("/")
        self.base_url = TESTNET_BASE if use_testnet else (override or PROD_BASE)
        self.timeout = timeout

    def klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 250,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> pd.DataFrame:
        params = {"symbol": symbol.upper(), "interval": interval, "limit": min(int(limit), 1000)}
        if start_time is not None:
            params["startTime"] = int(start_time)
        if end_time is not None:
            params["endTime"] = int(end_time)
        r = requests.get(f"{self.base_url}/api/v3/klines", params=params, timeout=self.timeout)
        r.raise_for_status()
        rows = r.json()
        cols = [
            "open_time", "open", "high", "low", "close", "volume", "close_time",
            "quote_volume", "trades", "taker_base", "taker_quote", "ignore"
        ]
        df = pd.DataFrame(rows, columns=cols)
        if df.empty:
            return pd.DataFrame(columns=cols)
        for c in ["open", "high", "low", "close", "volume", "quote_volume", "taker_base", "taker_quote"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["trades"] = pd.to_numeric(df["trades"], errors="coerce")
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
        return df

    def price(self, symbol: str) -> float:
        r = requests.get(
            f"{self.base_url}/api/v3/ticker/price",
            params={"symbol": symbol.upper()},
            timeout=self.timeout,
        )
        r.raise_for_status()
        return float(r.json()["price"])
