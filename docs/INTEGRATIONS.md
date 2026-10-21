# Open-source Integration Matrix — V1.1

| Project | Layer | V1.1 state | What is actually used |
|---|---|---:|---|
| Binance native | Market data + execution | ACTIVE | spot OHLCV/ticker, Paper/Testnet path |
| Lightweight Charts 5.2.1 | Web Terminal | ACTIVE | interactive candles, EMA, volume, RSI, trade markers; native canvas fallback |
| OpenBB / Open Data Platform V5 | Research data | IMPLEMENTED OPTIONAL | CBOE/Nasdaq equity history, CBOE quote, FRED series, SEC filings/statements |
| Native Research | Research | ACTIVE | backtest, benchmark, OOS scan, walk-forward, factor IC |
| Qlib | Research | SLOT | next heavy research adapter |
| Freqtrade | Execution | SLOT | future crypto dry-run/order lifecycle adapter |
| NautilusTrader | Execution | SLOT | future event-driven backend |
| rotki | Portfolio/Ledger | DESIGN REFERENCE | future wallet/exchange/on-chain ledger adapter |
| Ghostfolio | Portfolio UX | DESIGN REFERENCE | no Angular code embedded |
| Fincept Terminal | Product UX | DESIGN REFERENCE | no Qt code embedded |
| Stocknear | Product UX | DESIGN REFERENCE | no Svelte code embedded |
| LEAN | Multi-asset execution | DEFERRED | revisit only when stocks/options/futures require it |

## OpenBB V5 installation

Core trading does not require OpenBB. Install the research-data layer separately:

```bash
pip install -r requirements-openbb.txt
python run.py openbb-check
```

Provider smoke examples:

```bash
python run.py openbb-equity --symbol AAPL --provider cboe --interval 1d
python run.py openbb-macro --symbol GDP --start-date 2020-01-01
python run.py openbb-filings --symbol AAPL --form-type 10-K
```

FRED requires its upstream API credential for commands that require it. OpenBB provider coverage and upstream terms/rate limits remain provider-specific.

## Lightweight Charts integration

The Trade view loads the official standalone browser build from jsDelivr. If it cannot load, the terminal falls back to the previous native Canvas renderer, so chart CDN failure does not break status/research or trading.

The page includes TradingView attribution and enables the chart attribution logo.

## Next integration order

1. Qlib ResearchAdapter
2. Freqtrade dry-run adapter
3. Portfolio/Ledger adapter inspired by rotki
4. Nautilus only when the native/Freqtrade execution path is no longer enough
