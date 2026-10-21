# Changelog

## 1.2.2-agent-safety-alpha

- Added deterministic Skill Registry and autonomy levels.
- Added Promotion Gate over immutable research run IDs with expiring tickets.
- Added Agent Action Gateway with order/position budgets and live-money hard deny.
- Added immutable Decision Receipts.
- Replaced weak boolean approval with short-lived, payload-bound, one-time Human Approval Receipts.
- Added operator-only Circuit Breaker; Agent may only read status.
- Added restricted `scripts/agent_cli.py` and machine-readable `hermes/TOOL_POLICY.json`.
- Stopped globally loading project `.env`; Testnet keys are read only by execution/doctor paths.
- Added Agent safety/circuit/skill visibility to Web Terminal SYSTEM and Promotion status to RESEARCH.
- Added benchmark notes for xFutureTrade/Robinhood Agents and documented source claims vs project inferences.

## 1.2.1-integrity-alpha

- Added paginated Binance historical data, integrity checks, immutable research runs.
- Fixed Qlib split leakage, validation use, current inference separation.
- Defaulted native research fills to next-open.
- Hardened paper PnL/state and Binance Spot Testnet idempotency/reconciliation.
