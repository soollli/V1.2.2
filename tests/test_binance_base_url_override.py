from src.market import PROD_BASE, TESTNET_BASE, BinanceMarketData


def test_default_base_url(monkeypatch):
    monkeypatch.delenv("AI_QUANT_BINANCE_BASE_URL", raising=False)
    assert BinanceMarketData().base_url == PROD_BASE


def test_env_override(monkeypatch):
    monkeypatch.setenv("AI_QUANT_BINANCE_BASE_URL", "https://data-api.binance.vision")
    assert BinanceMarketData().base_url == "https://data-api.binance.vision"


def test_trailing_slash_stripped(monkeypatch):
    monkeypatch.setenv("AI_QUANT_BINANCE_BASE_URL", "https://data-api.binance.vision/")
    assert BinanceMarketData().base_url == "https://data-api.binance.vision"


def test_testnet_unaffected_by_override(monkeypatch):
    monkeypatch.setenv("AI_QUANT_BINANCE_BASE_URL", "https://data-api.binance.vision")
    assert BinanceMarketData(use_testnet=True).base_url == TESTNET_BASE
