from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import importlib.util
import pandas as pd

from ...core.contracts import AdapterInfo
from ...core.schemas import normalize_klines


class OpenBBUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenBBProviderStatus:
    name: str
    available: bool


class OpenBBDataFabricAdapter:
    """Optional OpenBB V5 research-data adapter.

    This adapter is intentionally NOT used for exchange execution or the bot's
    primary crypto trading feed. It exposes research-oriented provider calls
    behind a stable terminal interface.
    """

    info = AdapterInfo(
        kind="research_data",
        name="openbb",
        provider="OpenBB / Open Data Platform V5",
        description="Optional research data fabric for equity, macro and filings",
        live_money=False,
    )

    def __init__(self, obb_client: Any | None = None):
        if obb_client is not None:
            self.obb = obb_client
            self._injected = True
            return
        if importlib.util.find_spec("openbb") is None:
            raise OpenBBUnavailable(
                "OpenBB V5 is not installed. Install optional packages with: "
                "pip install -r requirements-openbb.txt"
            )
        from openbb import obb  # type: ignore
        self.obb = obb
        self._injected = False

    @staticmethod
    def installed() -> bool:
        return importlib.util.find_spec("openbb") is not None

    @staticmethod
    def _to_df(result: Any) -> pd.DataFrame:
        if hasattr(result, "to_dataframe"):
            try:
                df = result.to_dataframe(index=None)
            except TypeError:
                df = result.to_dataframe()
                if getattr(df.index, "name", None) is not None:
                    df = df.reset_index()
            return pd.DataFrame(df)
        if hasattr(result, "to_df"):
            return pd.DataFrame(result.to_df())
        if isinstance(result, pd.DataFrame):
            return result.copy()
        if isinstance(result, (list, tuple)):
            return pd.DataFrame(result)
        if isinstance(result, dict):
            return pd.DataFrame(result)
        raise TypeError(f"unsupported OpenBB result type: {type(result).__name__}")

    def coverage(self) -> dict[str, Any]:
        try:
            providers = getattr(getattr(self.obb, "coverage", None), "providers", {})
            if callable(providers):
                providers = providers()
            if providers is None:
                providers = {}
            return {"ok": True, "providers": providers}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "providers": {}}

    def equity_history(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
        interval: str = "1d",
        provider: str = "cboe",
    ) -> pd.DataFrame:
        """Return canonical OHLCV for research/backtest.

        V1.1 supports OpenBB V5 provider namespaces explicitly instead of the
        old shared-router API. Cboe supports 1d plus most-recent-day 1m data;
        Nasdaq supports daily OHLCV.
        """
        kwargs: dict[str, Any] = {"symbol": symbol, "provider": provider}
        if start_date:
            kwargs["start_date"] = start_date
        if end_date:
            kwargs["end_date"] = end_date

        if provider == "cboe":
            kwargs["interval"] = interval
            result = self.obb.cboe.equity.historical(**kwargs)
        elif provider == "nasdaq":
            if interval != "1d":
                raise ValueError("OpenBB Nasdaq equity history currently supports daily bars in this adapter")
            result = self.obb.nasdaq.equity.historical(**kwargs)
        else:
            raise ValueError(f"unsupported OpenBB equity provider in V1.1: {provider}")

        df = self._to_df(result)
        if "date" not in df.columns:
            if df.index.name == "date":
                df = df.reset_index()
            else:
                raise ValueError("OpenBB equity history returned no date column")
        date = pd.to_datetime(df["date"], utc=True, errors="coerce")
        out = pd.DataFrame({
            "open_time": date,
            "open": df["open"],
            "high": df["high"],
            "low": df["low"],
            "close": df["close"],
            "volume": df.get("volume", 0),
            "close_time": date,
        })
        return normalize_klines(out)

    def equity_quote(self, symbol: str, provider: str = "cboe") -> pd.DataFrame:
        if provider != "cboe":
            raise ValueError("V1.1 quote adapter currently supports provider='cboe'")
        result = self.obb.cboe.equity.quote(symbol=symbol, provider="cboe")
        return self._to_df(result)

    def fred_series(
        self,
        symbol: str | list[str],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        kwargs: dict[str, Any] = {"symbol": symbol, "provider": "fred"}
        if start_date:
            kwargs["start_date"] = start_date
        if end_date:
            kwargs["end_date"] = end_date
        result = self.obb.fred.economy.fred_series(**kwargs)
        return self._to_df(result)

    def company_filings(
        self,
        symbol: str,
        form_type: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        kwargs: dict[str, Any] = {"symbol": symbol, "provider": "sec"}
        if form_type:
            kwargs["form_type"] = form_type
        if start_date:
            kwargs["start_date"] = start_date
        if end_date:
            kwargs["end_date"] = end_date
        result = self.obb.sec.company_filings(**kwargs)
        return self._to_df(result)

    def financial_statements(self, symbol: str, statement_type: str = "income") -> pd.DataFrame:
        result = self.obb.sec.financial_statements(
            symbol=symbol,
            statement_type=statement_type,
            provider="sec",
        )
        return self._to_df(result)

    def health(self, network: bool = False) -> dict[str, Any]:
        base = {
            "ok": True,
            "adapter": self.info.name,
            "package_detected": self.installed() or self._injected,
            "network_checked": False,
        }
        if not network:
            return base
        try:
            # Cboe quote is keyless and is useful as a small end-to-end probe.
            df = self.equity_quote("AAPL")
            base.update({"network_checked": True, "rows": int(len(df))})
            return base
        except Exception as exc:
            base.update({"ok": False, "network_checked": True, "error": f"{type(exc).__name__}: {exc}"})
            return base
