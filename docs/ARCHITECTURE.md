# AI Quant Terminal — Locked Architecture V1.1

## Product target

A personal, AI-native Bloomberg-like terminal for research, paper/testnet execution and portfolio intelligence.
The system is deliberately modular: upstream open-source projects are adapters, not the owner of the terminal.

## Seven layers

```text
1. Web Terminal / Shell
   - TRADE / RESEARCH / DIAGNOSTICS / SYSTEM
   - TradingView Lightweight Charts for interactive market charts

2. AI / Agent Layer
   - Hermes reads snapshots, proposes hypotheses and orchestrates research
   - Agent never owns bar-by-bar trading state

3. Data Fabric
   - Binance native = exchange/trading truth source
   - OpenBB V5 = optional research data fabric
   - future: on-chain/news/local datasets

4. Research Engine
   - Native deterministic backtest/OOS/walk-forward/factor IC
   - future Qlib adapter for ML/alpha workflows

5. Portfolio / Ledger
   - current native state/trade ledger
   - future rotki-style exchange/wallet/on-chain accounting adapter

6. Execution Engine
   - Native Paper + Binance Spot Testnet
   - future Freqtrade dry-run / Nautilus event-driven adapters

7. Storage / Observability
   - JSON/CSV experiment and execution artifacts
   - status/snapshot/diagnostics exposed to Web + Hermes
```

## Hard ownership rules

### Binance owns trading truth
OpenBB does not replace Binance for the running crypto strategy. Orders and exchange-state-sensitive market data remain Binance-native.

### OpenBB owns research-data aggregation
OpenBB V5 is used for provider-style research queries such as CBOE/Nasdaq equity history, FRED macro data and SEC filings/statements.
It is optional and can be removed without breaking Paper/Testnet trading.

### Research and execution stay separated
A model can propose a strategy candidate, but it cannot directly mutate execution state. Strategy changes move through deterministic config/code and tests.

### UI frameworks are not mixed
Fincept, Stocknear and Ghostfolio remain product/UX references. Their Qt/Svelte/Angular shells are not embedded into this project.

## Stable contracts

### MarketDataProvider
Canonical OHLCV:
- open_time
- open/high/low/close
- volume
- close_time

### ResearchDataProvider
Research-oriented calls:
- equity history
- macro series
- company filings/statements

### ResearchEngine
- strategy report
- parameter scan / train-test
- walk-forward
- factor report

### ExecutionAdapter
- market buy/sell
- broker health
- Paper/Testnet only in the native implementation

## Integration gate

An upstream integration becomes implemented only when:
1. it has a real adapter, not only a registry label;
2. it can be disabled without breaking the core loop;
3. its boundary has unit tests with canonical schemas;
4. external/network failure has a clear fallback or error path;
5. real-money execution is not silently introduced.


## V1.2 ML Research boundary

Microsoft Qlib is integrated as a separate **ML Research Candidate Engine**. Native Research remains the deterministic validator. A Qlib score cannot place orders and cannot promote itself to Paper/Testnet.

```text
Binance/OpenBB -> Canonical Data -> Qlib ML Candidate
                                  -> Native Research Validator -> Execution
```

## V1.2.2 Agent Safety Plane

```text
Agnes / third-party LLM
        ↓
Hermes simple loop
        ↓
restricted agent_cli / future MCP surface
        ↓
Skill Registry
        ↓
Promotion Gate
        ↓
Action Gateway ── Circuit Breaker
        ↓
Human Approval Receipt (default, operator-only)
        ↓
Deterministic Execution Engine
```

The agent-facing surface is provider-agnostic. Agnes is not embedded into broker code. This allows Agnes/OpenAI/DeepSeek/etc. to be swapped without changing market-state ownership.

Operator-only controls and broker secrets are intentionally outside the Agent skill graph.
