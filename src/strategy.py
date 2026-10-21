from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import pandas as pd


class Signal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class SignalResult:
    signal: Signal
    reason: str
    price: float
    timestamp: str


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    avg_gain = up.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = down.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-12)
    return 100 - (100 / (1 + rs))


class EmaRsiStrategy:
    """Demo strategy used only to validate the pipeline.

    Replace this class with the user's actual strategy rules later.
    """

    def __init__(self, fast_ema=9, slow_ema=21, rsi_period=14, buy_rsi_min=50, sell_rsi_max=50):
        self.fast = fast_ema
        self.slow = slow_ema
        self.rsi_period = rsi_period
        self.buy_rsi_min = buy_rsi_min
        self.sell_rsi_max = sell_rsi_max

    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        if len(df) < max(self.slow + 3, self.rsi_period + 3):
            return SignalResult(Signal.HOLD, "insufficient_history", float(df.iloc[-1]["close"]), str(df.iloc[-1]["close_time"]))

        d = df.copy()
        d["ema_fast"] = d["close"].ewm(span=self.fast, adjust=False).mean()
        d["ema_slow"] = d["close"].ewm(span=self.slow, adjust=False).mean()
        d["rsi"] = rsi(d["close"], self.rsi_period)

        prev = d.iloc[-2]
        cur = d.iloc[-1]
        cross_up = prev.ema_fast <= prev.ema_slow and cur.ema_fast > cur.ema_slow
        cross_down = prev.ema_fast >= prev.ema_slow and cur.ema_fast < cur.ema_slow

        if cross_up and cur.rsi >= self.buy_rsi_min:
            sig = Signal.BUY
            reason = f"ema_cross_up+rsi={cur.rsi:.1f}"
        elif cross_down and cur.rsi <= self.sell_rsi_max:
            sig = Signal.SELL
            reason = f"ema_cross_down+rsi={cur.rsi:.1f}"
        else:
            sig = Signal.HOLD
            reason = f"no_entry ema_fast={cur.ema_fast:.2f} ema_slow={cur.ema_slow:.2f} rsi={cur.rsi:.1f}"

        return SignalResult(sig, reason, float(cur.close), str(cur.close_time))
