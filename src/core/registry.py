from __future__ import annotations
from dataclasses import asdict
import importlib.util
from typing import Any

from ..config import Settings
from ..adapters.data import BinanceDataAdapter, OpenBBDataFabricAdapter, OpenBBUnavailable
from ..adapters.research import NativeResearchAdapter, QlibResearchAdapter, QlibUnavailable
from ..adapters.execution import NativeExecutionAdapter
from ..agent import ActionGateway


OPTIONAL_INTEGRATIONS = {
    "openbb": {
        "kind": "research_data",
        "python_modules": ["openbb"],
        "status": "implemented_optional",
        "purpose": "OpenBB V5 multi-provider equity/macro/filings research data fabric",
        "install": "pip install -r requirements-openbb.txt",
    },
    "qlib": {
        "kind": "ml_research",
        "python_modules": ["qlib"],
        "status": "implemented_optional",
        "purpose": "Microsoft Qlib forecast-model research over canonical crypto panels",
        "install": "pip install -r requirements-qlib.txt",
    },
    "freqtrade": {
        "kind": "execution",
        "python_modules": ["freqtrade"],
        "status": "adapter_slot",
        "purpose": "crypto dry-run/exchange execution backend",
    },
    "nautilus": {
        "kind": "execution",
        "python_modules": ["nautilus_trader"],
        "status": "adapter_slot",
        "purpose": "event-driven high reliability backtest/live backend",
    },
}


class AdapterRegistry:
    def __init__(self, settings: Settings):
        self.settings = settings
        core = settings.raw.get("core", {})
        # Backward-compatible: data_provider remains the trading market feed.
        self.data_name = str(core.get("market_data_provider", core.get("data_provider", "binance"))).lower()
        self.research_data_name = str(core.get("research_data_provider", "openbb")).lower()
        self.research_name = str(core.get("research_engine", "native")).lower()
        self.ml_research_name = str(core.get("ml_research_engine", "qlib")).lower()
        self.execution_name = str(core.get("execution_engine", "native")).lower()

    def data(self, use_testnet: bool = False):
        """Primary trading market data. Keep Binance-native for exchange truth."""
        if self.data_name == "binance":
            return BinanceDataAdapter(use_testnet=use_testnet, cache_dir=self.settings.root / self.settings.raw.get("storage", {}).get("history_cache_dir", "data/cache/market"))
        raise ValueError(f"market data adapter '{self.data_name}' is not installed/enabled")

    market_data = data

    def research_data(self):
        if self.research_data_name == "openbb":
            return OpenBBDataFabricAdapter()
        if self.research_data_name in {"none", "disabled", "off"}:
            raise ValueError("research data provider is disabled")
        raise ValueError(f"research data adapter '{self.research_data_name}' is not installed/enabled")

    def research(self):
        if self.research_name == "native":
            return NativeResearchAdapter()
        raise ValueError(f"research adapter '{self.research_name}' is not installed/enabled")

    def ml_research(self):
        if self.ml_research_name == "qlib":
            return QlibResearchAdapter()
        if self.ml_research_name in {"none", "disabled", "off"}:
            raise ValueError("ML research engine is disabled")
        raise ValueError(f"ML research adapter '{self.ml_research_name}' is not installed/enabled")

    def execution(self, mode: str):
        if self.execution_name == "native":
            return NativeExecutionAdapter(self.settings, mode)
        raise ValueError(f"execution adapter '{self.execution_name}' is not installed/enabled")

    @staticmethod
    def _module_available(names: list[str]) -> bool:
        return any(importlib.util.find_spec(name) is not None for name in names)

    def capabilities(self) -> dict[str, Any]:
        data = self.data(False)
        research = self.research()
        openbb_detected = self._module_available(["openbb"])
        research_data = {
            "kind": "research_data",
            "name": self.research_data_name,
            "provider": "OpenBB / Open Data Platform V5" if self.research_data_name == "openbb" else self.research_data_name,
            "description": "optional research data fabric; never used as the exchange execution truth source",
            "implemented": self.research_data_name == "openbb",
            "python_package_detected": openbb_detected,
            "available": self.research_data_name == "openbb" and openbb_detected,
            "live_money": False,
        }
        optional = {}
        for name, meta in OPTIONAL_INTEGRATIONS.items():
            detected = self._module_available(meta["python_modules"])
            optional[name] = {
                **meta,
                "python_package_detected": detected,
                "implemented": meta["status"] == "implemented_optional",
                "enabled": (
                    (name == "openbb" and self.research_data_name == "openbb" and detected)
                    or (name == "qlib" and self.ml_research_name == "qlib" and detected)
                ),
            }
        return {
            "core": {
                "market_data": asdict(data.info),
                # Preserve the old key for clients written against V1.0 alpha.
                "data": asdict(data.info),
                "research_data": research_data,
                "research": asdict(research.info),
                "ml_research": {
                    "kind": "ml_research",
                    "name": self.ml_research_name,
                    "provider": "Microsoft Qlib" if self.ml_research_name == "qlib" else self.ml_research_name,
                    "description": "optional ML forecast-model layer; candidates must pass native OOS/walk-forward validation",
                    "implemented": self.ml_research_name == "qlib",
                    "python_package_detected": self._module_available(["qlib"]),
                    "available": self.ml_research_name == "qlib" and self._module_available(["qlib"]),
                    "live_money": False,
                },
                "execution": {
                    "kind": "execution",
                    "name": self.execution_name,
                    "provider": "Quant Terminal Native Broker",
                    "description": "paper + Binance Spot Testnet",
                    "live_money": False,
                },
            },
            "optional_integrations": optional,
            "research_integrity": {
                "binance_history_pagination": True,
                "kline_gap_duplicate_validation": True,
                "immutable_research_runs": True,
                "native_backtest_fill_mode": "next_open",
                "qlib_purged_time_split": True,
                "qlib_validation_model_selection": True,
                "qlib_current_inference_separated": True,
            },
            "web_terminal": {
                "chart_engine": "TradingView Lightweight Charts 5.2.1",
                "chart_delivery": "jsDelivr CDN with native-canvas fallback",
                "attribution_required": True,
                "loopback_only": True,
            },
            "agent_safety": ActionGateway(self.settings).capabilities(),
            "safety": {
                "live_money_enabled": False,
                "agent_direct_broker_access": False,
                "agent_execution_requires_gateway": True,
                "supported_execution_modes": ["paper", "binance_testnet"],
                "testnet_client_order_idempotency": True,
                "testnet_account_reconciliation": True,
                "client_side_stops_only": True,
            },
        }
