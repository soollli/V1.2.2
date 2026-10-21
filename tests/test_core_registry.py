from pathlib import Path
import pandas as pd

from src.config import load_settings
from src.core.registry import AdapterRegistry
from src.core.schemas import normalize_klines


def _settings(tmp_path: Path):
    cfg = tmp_path / 'config.yaml'
    cfg.write_text('''
project: {name: core-test}
core: {data_provider: binance, research_engine: native, execution_engine: native}
market: {symbol: BTCUSDT, interval: 1m, history_bars: 80, poll_seconds: 5}
strategy: {name: ema_rsi_demo, fast_ema: 9, slow_ema: 21, rsi_period: 14, buy_rsi_min: 50, sell_rsi_max: 50}
risk: {quote_order_size: 50.0, max_position_quote: 250.0, stop_loss_pct: 0.02, take_profit_pct: 0.04, fee_rate: 0.001, slippage_bps: 2}
broker: {mode: paper, initial_quote_balance: 10000.0}
storage:
  state_file: data/state_{mode}.json
  trades_file: logs/trades_{mode}.csv
  events_file: logs/events_{mode}.log
''', encoding='utf-8')
    return load_settings(str(cfg))


def test_registry_exposes_active_core_and_optional_slots(tmp_path: Path):
    r = AdapterRegistry(_settings(tmp_path))
    caps = r.capabilities()
    assert caps['core']['data']['name'] == 'binance'
    assert caps['core']['research']['name'] == 'native'
    assert caps['core']['execution']['name'] == 'native'
    assert caps['safety']['live_money_enabled'] is False
    assert {'openbb', 'qlib', 'freqtrade', 'nautilus'} <= set(caps['optional_integrations'])
    assert caps['core']['research_data']['name'] == 'openbb'
    assert caps['optional_integrations']['openbb']['implemented'] is True
    assert caps['web_terminal']['chart_engine'].startswith('TradingView Lightweight Charts')


def test_native_execution_is_paper_only_without_credentials(tmp_path: Path):
    r = AdapterRegistry(_settings(tmp_path))
    ex = r.execution('paper')
    fill = ex.market_buy('BTCUSDT', 100.0, 100.0)
    assert fill.side == 'BUY'
    assert fill.base_qty > 0
    assert ex.health()['live_money'] is False


def test_canonical_kline_normalization():
    df = pd.DataFrame({
        'open_time': ['2026-01-01T00:00:00Z'],
        'open': ['1'], 'high': ['2'], 'low': ['0.5'], 'close': ['1.5'], 'volume': ['10'],
        'close_time': ['2026-01-01T00:01:00Z'],
    })
    out = normalize_klines(df)
    assert float(out.iloc[0]['close']) == 1.5
    assert str(out.iloc[0]['open_time'].tz) == 'UTC'


def test_capabilities_expose_agent_safety_plane():
    from pathlib import Path
    import yaml
    from src.config import Settings
    from src.core.registry import AdapterRegistry
    root = Path(__file__).parents[1]
    raw = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    caps = AdapterRegistry(Settings(raw=raw, root=root)).capabilities()
    a = caps["agent_safety"]
    assert a["architecture"] == "single_agent_loop_plus_deterministic_skills"
    assert a["gateway"]["broker_secret_access"] is False
    assert a["policy"]["level"] == "propose"
    assert caps["safety"]["agent_direct_broker_access"] is False
