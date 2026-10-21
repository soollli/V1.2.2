from pathlib import Path
import pandas as pd

from src.config import load_settings
from src.dashboard import build_chart_payload


class FakeMarket:
    def klines(self, symbol, interval, limit):
        n = 80
        t = pd.date_range('2026-01-01', periods=n, freq='min', tz='UTC')
        close = pd.Series([100 + i * 0.1 for i in range(n)], dtype=float)
        return pd.DataFrame({
            'open_time': t,
            'open': close - 0.1,
            'high': close + 0.4,
            'low': close - 0.4,
            'close': close,
            'volume': 1000 + close,
            'close_time': t,
        })


def test_chart_payload_has_indicators(tmp_path: Path):
    cfg = tmp_path / 'config.yaml'
    cfg.write_text('''
project: {name: test}
market: {symbol: BTCUSDT, interval: 1m, history_bars: 80, poll_seconds: 5}
strategy: {name: ema_rsi_demo, fast_ema: 9, slow_ema: 21, rsi_period: 14, buy_rsi_min: 50, sell_rsi_max: 50}
risk: {quote_order_size: 50.0, max_position_quote: 250.0, stop_loss_pct: 0.02, take_profit_pct: 0.04, fee_rate: 0.001, slippage_bps: 2}
broker: {mode: paper, initial_quote_balance: 10000.0}
storage:
  state_file: data/state_{mode}.json
  trades_file: logs/trades_{mode}.csv
  events_file: logs/events_{mode}.log
''', encoding='utf-8')
    s = load_settings(str(cfg))
    out = build_chart_payload(s, 'paper', '1m', 80, market=FakeMarket())
    assert out['symbol'] == 'BTCUSDT'
    assert len(out['candles']) == 80
    assert out['candles'][-1]['ema_fast'] is not None
    assert out['candles'][-1]['ema_slow'] is not None
    assert out['candles'][-1]['rsi'] is not None


def test_dashboard_html_has_research_and_diagnostics_tabs():
    from src.dashboard import HTML
    assert 'RESEARCH' in HTML
    assert 'DIAGNOSTICS' in HTML
    assert 'SYSTEM' in HTML
    assert '/api/capabilities' in HTML
    assert 'equityChart' in HTML
    assert 'factorRows' in HTML
    assert 'lightweight-charts@5.2.1' in HTML
    assert 'Lightweight Charts' in HTML
    assert 'createSeriesMarkers' in HTML


def test_dashboard_contains_agent_safety_and_promotion_gate():
    from src.dashboard import HTML
    assert "Agent Safety Plane" in HTML
    assert "Promotion Gate" in HTML
    assert "agentSkillRows" in HTML
    assert "promotionState" in HTML
