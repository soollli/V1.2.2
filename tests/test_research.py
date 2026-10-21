import numpy as np
import pandas as pd

from src.research import strategy_report, parameter_scan, walk_forward


def sample_df(n=700):
    t = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    x = np.arange(n)
    close = 100 + 0.03 * x + 4 * np.sin(x / 18) + 1.5 * np.sin(x / 5)
    return pd.DataFrame({
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 1000.0,
        "close_time": t,
    })


STRATEGY = {"name":"ema_rsi_demo","fast_ema":9,"slow_ema":21,"rsi_period":14,"buy_rsi_min":50,"sell_rsi_max":50}
RISK = {"quote_order_size":1000.0,"max_position_quote":1000.0,"stop_loss_pct":0.03,"take_profit_pct":0.05,"fee_rate":0.001,"slippage_bps":2}


def test_research_report_has_benchmark_and_risk_metrics():
    r = strategy_report(sample_df(), STRATEGY, RISK, 10000.0, "1h")
    assert "benchmark_buy_hold" in r
    assert "max_drawdown_pct" in r["strategy"]
    assert "profit_factor" in r["strategy"]
    assert r["sample"]["annualization_basis"] == "crypto_24x7_365d"


def test_parameter_scan_has_oos_rows():
    r = parameter_scan(sample_df(), STRATEGY, RISK, 10000.0, "1h")
    assert r["rows"]
    assert "generalization_gap_pct" in r["rows"][0]


def test_walkforward_returns_folds():
    r = walk_forward(sample_df(900), STRATEGY, RISK, 10000.0, "1h", folds=3)
    assert len(r["folds"]) == 3


def test_strategy_report_has_web_timeseries():
    r = strategy_report(sample_df(), STRATEGY, RISK, 10000.0, "1h")
    assert r["timeseries"]["rows"]
    assert "drawdown_pct" in r["timeseries"]["rows"][-1]
    assert "market_regime" in r["timeseries"]
