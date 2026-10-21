# Open-source Fusion Status — Core V1.2.2

Source of truth for what is actually integrated.

| Project | Locked responsibility | Status |
|---|---|---:|
| TradingView Lightweight Charts | Web market charts | ACTIVE (CDN + native canvas fallback) |
| OpenBB / OpenBQ V5 | Research Data Fabric | IMPLEMENTED OPTIONAL |
| Microsoft Qlib | ML candidate research | IMPLEMENTED OPTIONAL + PURGED VALIDATION |
| Binance native adapter | Exchange market truth + paginated history + testnet | ACTIVE |
| Native Quant Core | Backtest/OOS/walk-forward/factors/validation | ACTIVE |
| Freqtrade | Crypto dry-run/order lifecycle sidecar | SLOT |
| NautilusTrader | Event-driven execution sidecar | SLOT |
| rotki | Portfolio/on-chain ledger | FUTURE ADAPTER |
| Ghostfolio | Portfolio UX/data-model reference | REFERENCE |
| Stocknear | Screener/research UX reference | REFERENCE |
| Fincept Terminal | Bloomberg-like information architecture reference | REFERENCE |
| LEAN | Future multi-asset option | DEFERRED |

## Boundaries

1. Binance remains the trading/execution truth source.
2. OpenBB never places orders.
3. Qlib never places orders and cannot self-promote a candidate.
4. Native Research remains the independent validation gate.
5. Hermes researches/diagnoses/orchestrates; it does not own live position state.
6. No live-money command exists.
7. Freqtrade/Nautilus remain sidecar candidates, not dependencies of the core environment.

## Agentic safety plane

Not an external dependency: V1.2.2 adds a native Skill Registry, Promotion Gate, Action Gateway, one-time out-of-band Human Approval Receipts, Circuit Breaker, Decision Receipts and restricted Hermes CLI. Agnes/other LLMs remain provider-agnostic reasoning layers and do not own broker state.
