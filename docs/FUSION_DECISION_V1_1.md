# Fusion Decision V1.1

## Re-analysis before fusion

The terminal should not become a mega-fork of OpenBB + Fincept + Ghostfolio + rotki + LEAN + multiple trading engines.
The previously agreed framework is kept and each upstream project has one owner role.

### Keep / integrate now

- **Lightweight Charts** -> Web Terminal chart engine.
- **OpenBB V5** -> Research Data Fabric only.
- **Native Research** -> deterministic research baseline and acceptance test for future Qlib.
- **Native Paper/Testnet** -> execution baseline and acceptance test for future Freqtrade/Nautilus.

### Keep as next adapters

- **Qlib** -> ML/alpha research, not chart/UI or order execution.
- **Freqtrade** -> first external crypto dry-run execution adapter.
- **NautilusTrader** -> later event-driven/high-reliability backend when needed.
- **rotki** -> later portfolio/on-chain ledger adapter.

### Reference only

- **Fincept Terminal** -> product information architecture.
- **Stocknear** -> screener/research UX.
- **Ghostfolio** -> portfolio UX/data-model ideas.
- **LEAN** -> defer until multi-asset stocks/options/futures become a real requirement.

## Why OpenBB is separate from Binance

The running crypto strategy needs exchange-native truth for bar timing, prices and eventual order-state reconciliation. OpenBB is a provider aggregation layer for research. Combining the two behind one active feed would blur execution truth and research convenience.

Therefore Core V1.1 has:

```text
MarketDataProvider: Binance
ResearchDataProvider: OpenBB (optional)
ResearchEngine: Native
ExecutionAdapter: Native Paper/Testnet
```

## Why Qlib is not fused in V1.1

Qlib changes the research runtime and dependency surface significantly. The correct gate is to first make the ResearchData boundary real, then connect Qlib in V1.2 and compare its outputs against the existing deterministic Native Research baseline.

## What counts as "fused"

A project is no longer called a slot only when it has:
- real source adapter code;
- stable terminal contract mapping;
- capability reporting;
- installation/run instructions;
- boundary tests;
- failure behavior that does not break unrelated terminal layers.

V1.1 meets this bar for Lightweight Charts and OpenBB (the OpenBB Python packages remain optional dependencies).
