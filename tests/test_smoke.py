import numpy as np
import pandas as pd
from src.backtest import run_backtest


def synthetic_df(n=300):
    x = np.arange(n)
    close = 100 + 0.03 * x + 4 * np.sin(x / 8)
    t = pd.date_range("2026-01-01", periods=n, freq="min", tz="UTC")
    return pd.DataFrame({
        "open_time": t,
        "open": close,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": 1000.0,
        "close_time": t,
    })


def test_pipeline_smoke():
    df = synthetic_df()
    strategy = {"name": "ema_rsi_demo", "fast_ema": 5, "slow_ema": 12, "rsi_period": 7, "buy_rsi_min": 45, "sell_rsi_max": 55}
    risk = {"quote_order_size": 100.0, "max_position_quote": 200.0, "stop_loss_pct": 0.03, "take_profit_pct": 0.05, "fee_rate": 0.001, "slippage_bps": 2}
    r = run_backtest(df, strategy, risk, 10000.0)
    assert r.end_equity > 0
    assert r.trades > 0
