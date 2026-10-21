from __future__ import annotations
from typing import Any
import pandas as pd
from ...core.contracts import AdapterInfo
from ...research import strategy_report, parameter_scan, walk_forward
from ...factors import analyze_factor_matrix


class NativeResearchAdapter:
    info = AdapterInfo(
        kind="research",
        name="native",
        provider="Quant Terminal Native",
        description="Deterministic backtest, OOS scan, walk-forward and cross-sectional factor research",
    )

    def strategy_report(self, df: pd.DataFrame, strategy_cfg: dict, risk_cfg: dict,
                        initial_quote: float, interval: str) -> dict:
        return strategy_report(df, strategy_cfg, risk_cfg, initial_quote, interval)

    def parameter_scan(self, df: pd.DataFrame, strategy_cfg: dict, risk_cfg: dict,
                       initial_quote: float, interval: str) -> dict:
        return parameter_scan(df, strategy_cfg, risk_cfg, initial_quote, interval)

    def walk_forward(self, df: pd.DataFrame, strategy_cfg: dict, risk_cfg: dict,
                     initial_quote: float, interval: str) -> dict:
        return walk_forward(df, strategy_cfg, risk_cfg, initial_quote, interval)

    def factor_report(self, closes: pd.DataFrame, cfg: dict) -> dict:
        return analyze_factor_matrix(
            closes,
            momentum_period=int(cfg.get("momentum_period", 20)),
            vol_period=int(cfg.get("vol_period", 20)),
            reversal_period=int(cfg.get("reversal_period", 5)),
            forward_windows=cfg.get("forward_windows", [5, 10, 20]),
            min_assets=int(cfg.get("min_assets", 5)),
            group_min_assets=int(cfg.get("group_min_assets", 4)),
        )

    def health(self) -> dict[str, Any]:
        return {"ok": True, "adapter": self.info.name, "deterministic": True}
