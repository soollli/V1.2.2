from __future__ import annotations
from typing import Any
from ...brokers import PaperBroker, BinanceSpotTestnetBroker
from ...config import Settings, env_testnet_credentials
from ...core.contracts import AdapterInfo


class NativeExecutionAdapter:
    """Execution boundary around paper and Binance Spot Testnet brokers."""
    info = AdapterInfo(
        kind="execution",
        name="native",
        provider="Quant Terminal Native Broker",
        description="Paper fills or Binance Spot Testnet orders with idempotent client order ids",
        live_money=False,
    )

    def __init__(self, settings: Settings, mode: str):
        self.settings = settings
        self.mode = mode
        if mode == "paper":
            self.broker = PaperBroker(settings.risk["fee_rate"], settings.risk["slippage_bps"])
        elif mode == "binance_testnet":
            key, secret = env_testnet_credentials(self.settings.root)
            self.broker = BinanceSpotTestnetBroker(key, secret)
        else:
            raise ValueError("Core exposes paper and binance_testnet only; live-money execution is intentionally disabled.")

    def market_buy(self, symbol: str, quote_amount: float, market_price: float | None = None):
        return self.broker.market_buy(symbol, quote_amount, market_price)

    def market_sell(self, symbol: str, base_qty: float, market_price: float | None = None):
        return self.broker.market_sell(symbol, base_qty, market_price)

    def account_balances(self, symbol: str) -> dict:
        if self.mode != "binance_testnet":
            raise RuntimeError("account reconciliation is only available for binance_testnet")
        return self.broker.account_balances(symbol)

    def query_order(self, symbol: str, **kwargs):
        if self.mode != "binance_testnet":
            raise RuntimeError("order query is only available for binance_testnet")
        return self.broker.query_order(symbol, **kwargs)

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "adapter": self.info.name,
            "mode": self.mode,
            "live_money": False,
            "client_order_idempotency": self.mode == "binance_testnet",
            "account_reconciliation": self.mode == "binance_testnet",
        }
