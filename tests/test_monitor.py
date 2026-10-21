from pathlib import Path

from src.config import load_settings
from src.monitor import build_status
from src.state import PortfolioState


def test_mode_separated_status(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text('''
project: {name: test}
market: {symbol: BTCUSDT, interval: 1m, history_bars: 50, poll_seconds: 5}
strategy: {name: ema_rsi_demo, fast_ema: 9, slow_ema: 21, rsi_period: 14, buy_rsi_min: 50, sell_rsi_max: 50}
risk: {quote_order_size: 50.0, max_position_quote: 250.0, stop_loss_pct: 0.02, take_profit_pct: 0.04, fee_rate: 0.001, slippage_bps: 2}
broker: {mode: paper, initial_quote_balance: 10000.0}
storage:
  state_file: data/state_{mode}.json
  trades_file: logs/trades_{mode}.csv
  events_file: logs/events_{mode}.log
''', encoding='utf-8')
    s = load_settings(str(cfg))
    st = PortfolioState(quote_balance=9999, last_price=123.0, last_signal='BUY')
    st.save(tmp_path / 'data' / 'state_paper.json')
    out = build_status(s, 'paper')
    assert out['state']['quote_balance'] == 9999
    assert out['state']['last_price'] == 123.0
    assert out['mode'] == 'paper'
    assert out['adapters']['data']['name'] == 'binance'
    assert out['adapters']['research']['name'] == 'native'
