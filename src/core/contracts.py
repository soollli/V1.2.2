from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
import pandas as pd


@dataclass(frozen=True)
class AdapterInfo:
    kind: str
    name: str
    provider: str
    description: str
    live_money: bool = False


@runtime_checkable
class MarketDataProvider(Protocol):
    info: AdapterInfo

    def klines(self, symbol: str, interval: str, limit: int = 250) -> pd.DataFrame: ...
    def history(self, symbol: str, interval: str, bars: int, *, closed_only: bool = True, use_cache: bool = True, strict: bool = True) -> pd.DataFrame: ...
    def price(self, symbol: str) -> float: ...
    def health(self) -> dict[str, Any]: ...


@runtime_checkable
class ExecutionAdapter(Protocol):
    info: AdapterInfo

    def market_buy(self, symbol: str, quote_amount: float, market_price: float | None = None): ...
    def market_sell(self, symbol: str, base_qty: float, market_price: float | None = None): ...
    def health(self) -> dict[str, Any]: ...


@runtime_checkable
class ResearchEngine(Protocol):
    info: AdapterInfo

    def strategy_report(self, df: pd.DataFrame, strategy_cfg: dict, risk_cfg: dict,
                        initial_quote: float, interval: str) -> dict: ...
    def parameter_scan(self, df: pd.DataFrame, strategy_cfg: dict, risk_cfg: dict,
                       initial_quote: float, interval: str) -> dict: ...
    def walk_forward(self, df: pd.DataFrame, strategy_cfg: dict, risk_cfg: dict,
                     initial_quote: float, interval: str) -> dict: ...
    def factor_report(self, closes: pd.DataFrame, cfg: dict) -> dict: ...
    def health(self) -> dict[str, Any]: ...


@runtime_checkable
class ResearchDataProvider(Protocol):
    info: AdapterInfo

    def equity_history(self, symbol: str, start_date: str | None = None, end_date: str | None = None,
                       interval: str = "1d", provider: str = "cboe") -> pd.DataFrame: ...
    def fred_series(self, symbol: str | list[str], start_date: str | None = None,
                    end_date: str | None = None) -> pd.DataFrame: ...
    def company_filings(self, symbol: str, form_type: str | list[str] | None = None,
                        start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame: ...
    def health(self, network: bool = False) -> dict[str, Any]: ...


@runtime_checkable
class MLResearchEngine(Protocol):
    info: AdapterInfo

    def ml_report(self, closes: pd.DataFrame, cfg: dict) -> dict: ...
    def health(self) -> dict[str, Any]: ...
