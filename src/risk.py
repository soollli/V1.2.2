from __future__ import annotations
from dataclasses import dataclass
from .state import PortfolioState


@dataclass
class RiskDecision:
    allowed: bool
    action: str
    reason: str
    quote_amount: float = 0.0
    base_qty: float = 0.0


class RiskManager:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def stop_or_take_profit(self, state: PortfolioState, price: float):
        if state.base_qty <= 0 or state.avg_entry <= 0:
            return None
        ret = price / state.avg_entry - 1
        if ret <= -float(self.cfg["stop_loss_pct"]):
            return RiskDecision(True, "SELL", f"stop_loss {ret:.2%}", base_qty=state.base_qty)
        if ret >= float(self.cfg["take_profit_pct"]):
            return RiskDecision(True, "SELL", f"take_profit {ret:.2%}", base_qty=state.base_qty)
        return None

    def on_signal(self, signal: str, state: PortfolioState, price: float):
        if signal == "BUY":
            if state.base_qty > 0:
                return RiskDecision(False, "HOLD", "already_in_position")
            quote_amt = min(
                float(self.cfg["quote_order_size"]),
                float(self.cfg["max_position_quote"]),
                state.quote_balance,
            )
            if quote_amt <= 0:
                return RiskDecision(False, "HOLD", "no_quote_balance")
            return RiskDecision(True, "BUY", "signal_buy", quote_amount=quote_amt)

        if signal == "SELL":
            if state.base_qty <= 0:
                return RiskDecision(False, "HOLD", "no_position")
            return RiskDecision(True, "SELL", "signal_sell", base_qty=state.base_qty)

        return RiskDecision(False, "HOLD", "hold")
