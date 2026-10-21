import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from src.adapters.data.binance import BinanceDataAdapter
from src.adapters.research.qlib import QlibResearchAdapter, build_qlib_panel, split_panel
from src.backtest import _apply_buy, _apply_sell, run_backtest
from src.brokers import BinanceSpotTestnetBroker, PaperBroker
from src.research_runs import archive_research_run
from src.state import PortfolioState


def _ohlcv(n=2600, freq="h"):
    t = pd.date_range("2025-01-01", periods=n, freq=freq, tz="UTC")
    close = 100 + np.arange(n) * 0.01
    return pd.DataFrame({
        "open_time": t,
        "open": close - 0.1,
        "high": close + 0.2,
        "low": close - 0.2,
        "close": close,
        "volume": 1000.0,
        "close_time": t + pd.Timedelta(hours=1) - pd.Timedelta(milliseconds=1),
        "quote_volume": 1.0,
        "trades": 1,
        "taker_base": 1.0,
        "taker_quote": 1.0,
        "ignore": 0,
    })


class FakeHistoryClient:
    def __init__(self, df):
        self.df = df.copy()
        self.calls = []

    def klines(self, symbol, interval, limit=250, *, start_time=None, end_time=None):
        self.calls.append({"limit": limit, "start_time": start_time, "end_time": end_time})
        x = self.df
        if start_time is not None:
            x = x[(x["open_time"].astype("int64") // 1_000_000) >= int(start_time)]
            return x.head(limit).copy()
        if end_time is not None:
            x = x[(x["open_time"].astype("int64") // 1_000_000) <= int(end_time)]
        return x.tail(limit).copy()


def _closes(rows=220, assets=6):
    idx = pd.date_range("2026-01-01", periods=rows, freq="h", tz="UTC")
    x = np.arange(rows, dtype=float)
    return pd.DataFrame({
        f"A{j}": 100 + (j + 1) * 0.03 * x + np.sin(x / (5 + j)) * (1 + j * 0.2)
        for j in range(assets)
    }, index=idx)


class FakeLinear:
    def __init__(self, estimator="ridge", alpha=1.0, fit_intercept=True, include_valid=False):
        self.alpha = alpha
        self.fit_intercept = fit_intercept
        self.include_valid = include_valid
        self.beta = None

    def fit(self, dataset):
        parts = [dataset.prepare("train", col_set=["feature", "label"])]
        if self.include_valid:
            parts.append(dataset.prepare("valid", col_set=["feature", "label"]))
        df = pd.concat(parts)
        x = df["feature"].values
        y = df["label"].values[:, 0]
        if self.fit_intercept:
            x = np.c_[x, np.ones(len(x))]
        reg = np.eye(x.shape[1]) * float(self.alpha)
        if self.fit_intercept:
            reg[-1, -1] = 0.0
        self.beta = np.linalg.pinv(x.T @ x + reg) @ x.T @ y
        return self

    def predict(self, dataset, segment="test"):
        xdf = dataset.prepare(segment, col_set="feature")
        x = xdf.values
        if self.fit_intercept:
            x = np.c_[x, np.ones(len(x))]
        return pd.Series(x @ self.beta, index=xdf.index)


def test_clean_process_import_has_no_cycle():
    cmd = [sys.executable, "-c", "from src.adapters.research.qlib import QlibResearchAdapter; from src.adapters.data.binance import BinanceDataAdapter; print('OK')"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    assert "OK" in out.stdout


def test_paper_roundtrip_realized_pnl_includes_both_fees():
    broker = PaperBroker(fee_rate=0.001, slippage_bps=0)
    st = PortfolioState(quote_balance=1000.0)
    buy = broker.market_buy("SIM", 100.0, 100.0)
    _apply_buy(st, buy)
    sell = broker.market_sell("SIM", st.base_qty, 100.0)
    _apply_sell(st, sell)
    assert abs(st.realized_pnl - (-0.1999)) < 1e-6
    assert abs(st.quote_balance - 999.8001) < 1e-6


def test_backtest_default_fill_occurs_after_signal_bar():
    n = 300
    x = np.arange(n)
    close = 100 + 0.03 * x + 4 * np.sin(x / 8)
    t = pd.date_range("2026-01-01", periods=n, freq="min", tz="UTC")
    df = pd.DataFrame({"open_time": t, "open": close, "high": close+.5, "low": close-.5, "close": close, "volume": 1000, "close_time": t})
    strategy = {"name":"ema_rsi_demo","fast_ema":5,"slow_ema":12,"rsi_period":7,"buy_rsi_min":45,"sell_rsi_max":55}
    risk = {"quote_order_size":100.,"max_position_quote":200.,"stop_loss_pct":.03,"take_profit_pct":.05,"fee_rate":.001,"slippage_bps":0}
    r = run_backtest(df, strategy, risk, 10000)
    assert r.fill_mode == "next_open"
    assert r.round_trips
    assert pd.Timestamp(r.round_trips[0]["entry_time"]) > pd.Timestamp(r.round_trips[0]["signal_time"])


def test_binance_history_paginates_past_1000(tmp_path):
    adapter = BinanceDataAdapter(cache_dir=tmp_path)
    fake = FakeHistoryClient(_ohlcv())
    adapter.client = fake
    out = adapter.history("BTCUSDT", "1h", 2200, closed_only=False, use_cache=False, strict=True)
    assert len(out) == 2200
    assert len(fake.calls) >= 3
    assert any(c["end_time"] is not None for c in fake.calls[1:])
    assert out.attrs["requested_bars"] == 2200


def test_qlib_split_purges_forward_label_boundary_and_current_is_newer():
    closes = _closes()
    panel = build_qlib_panel(closes, forward_bars=5, min_assets=5)
    seg, meta = split_panel(panel, purge_bars=5, embargo_bars=1, return_meta=True)
    times = pd.Index(panel.index.get_level_values("datetime").unique()).sort_values()
    train_end_i = times.get_loc(seg["train"][1])
    valid_start_i = times.get_loc(seg["valid"][0])
    valid_end_i = times.get_loc(seg["valid"][1])
    test_start_i = times.get_loc(seg["test"][0])
    assert train_end_i + 5 < valid_start_i
    assert valid_end_i + 5 < test_start_i
    assert meta["purged_before_valid"] >= 5

    report = QlibResearchAdapter(model_factory=FakeLinear).ml_report(closes, {"min_assets":5,"forward_bars":5,"alpha_grid":[0.1,1.0]})
    assert report["validation_selection"]["selected_alpha"] in {0.1, 1.0}
    assert pd.Timestamp(report["current_inference"]["timestamp"]) > pd.Timestamp(report["latest_labeled_test"]["timestamp"])
    assert all(x["realized_forward_return_pct"] is None for x in report["current_inference"]["ranking"])


def test_research_run_is_immutable_bundle(tmp_path):
    df = pd.DataFrame({"x": [1.0, 2.0]}, index=pd.date_range("2026-01-01", periods=2, tz="UTC"))
    (tmp_path / "VERSION").write_text("test\n")
    run_id, run_dir = archive_research_run(tmp_path, kind="unit", report={"ok": True}, config={"a": 1}, data=df)
    assert run_id in run_dir.name
    for name in ["manifest.json", "config.json", "data_manifest.json", "environment.json", "report.json"]:
        assert (run_dir / name).exists()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["reproducibility"]["immutable_run_directory"] is True
    assert manifest["data_sha256"]


def test_testnet_unknown_order_queries_same_client_id_without_resubmit(monkeypatch):
    broker = BinanceSpotTestnetBroker("k", "s")
    calls = []

    def fake_signed(method, path, params):
        calls.append((method, path, dict(params)))
        if method == "POST":
            raise requests.Timeout("simulated")
        return {"symbol": "BTCUSDT", "orderId": 7, "status": "FILLED"}

    monkeypatch.setattr(broker, "_signed", fake_signed)
    raw = broker._place_market("BTCUSDT", {"side": "BUY", "quoteOrderQty": "10"})
    assert raw["orderId"] == 7
    assert sum(1 for c in calls if c[0] == "POST") == 1
    posted_id = next(c[2]["newClientOrderId"] for c in calls if c[0] == "POST")
    queried_id = next(c[2]["origClientOrderId"] for c in calls if c[0] == "GET")
    assert posted_id == queried_id


def test_testnet_fill_normalizes_quote_and_base_commissions(monkeypatch):
    broker = BinanceSpotTestnetBroker("k", "s")
    monkeypatch.setattr(broker, "_symbol_info", lambda symbol: {"baseAsset": "BTC", "quoteAsset": "USDT", "filters": []})
    buy_raw = {
        "orderId": 1, "executedQty": "1.0", "cummulativeQuoteQty": "100.0",
        "fills": [{"commission": "0.001", "commissionAsset": "BTC"}],
    }
    buy = broker._normalize_fill("BTCUSDT", "BUY", buy_raw, 100.0)
    assert abs(buy.base_qty - 0.999) < 1e-12
    assert buy.quote_qty == 100.0
    assert buy.fee_quote == 0.0

    sell_raw = {
        "orderId": 2, "executedQty": "0.999", "cummulativeQuoteQty": "99.9",
        "fills": [{"commission": "0.0999", "commissionAsset": "USDT"}],
    }
    sell = broker._normalize_fill("BTCUSDT", "SELL", sell_raw, 100.0)
    assert abs(sell.quote_qty - 99.8001) < 1e-9
    assert abs(sell.fee_quote - 0.0999) < 1e-12


def test_dashboard_rejects_non_loopback(tmp_path):
    from src.config import load_settings
    from src.dashboard import run_dashboard
    cfg = tmp_path / "config.yaml"
    cfg.write_text('''
project: {name: test}
market: {symbol: BTCUSDT, interval: 1m, history_bars: 80, poll_seconds: 5}
strategy: {name: ema_rsi_demo, fast_ema: 9, slow_ema: 21, rsi_period: 14, buy_rsi_min: 50, sell_rsi_max: 50}
risk: {quote_order_size: 50.0, max_position_quote: 250.0, stop_loss_pct: 0.02, take_profit_pct: 0.04, fee_rate: 0.001, slippage_bps: 2}
broker: {mode: paper, initial_quote_balance: 10000.0}
storage:
  state_file: "data/state_{mode}.json"
  trades_file: "logs/trades_{mode}.csv"
  events_file: "logs/events_{mode}.log"
''')
    s = load_settings(str(cfg))
    try:
        run_dashboard(s, host="0.0.0.0")
        assert False, "non-loopback bind should be blocked"
    except ValueError as exc:
        assert "loopback-only" in str(exc)
