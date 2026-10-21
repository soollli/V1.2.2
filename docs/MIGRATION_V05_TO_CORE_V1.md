# Migration: Quant MVP v0.5 -> AI Quant Terminal Core V1

No user workflow was intentionally removed.

Old commands remain:

```bash
python run.py paper
python run.py dashboard --mode paper --open-browser
python run.py research --bars 1000
python run.py scan --bars 1000
python run.py walkforward --bars 1000
python run.py factors --bars 1000
```

New commands:

```bash
python run.py capabilities
python run.py terminal --mode paper
```

`terminal` is a convenience alias for opening the read-only Web terminal. It does **not** start the trading engine; run `paper` separately.

The important migration is internal:

```text
before:
Dashboard -> Binance directly
TradingEngine -> Binance/Broker directly
Research CLI -> native functions directly

after:
Dashboard -> DataProvider
TradingEngine -> DataProvider + ExecutionAdapter
Research CLI -> ResearchEngine
              ^
              |
        Adapter Registry
```
