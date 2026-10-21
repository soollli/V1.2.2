# Hermes Quant Agent SOP — V1.2.2

## Architecture rule

Use one strong reasoning loop plus deterministic skills. Do not create specialist LLM agents merely because a task has different domains.

## Default cycle: Define → Research → Doubt → Promote → Propose

1. Define a falsifiable hypothesis and acceptance criteria.
2. Run deterministic research through the restricted Agent CLI.
3. Read benchmark/OOS/walk-forward/cost/drawdown evidence.
4. Doubt the result: leakage, sharp parameter peaks, regime concentration, weak trade count, execution gap.
5. Record immutable run IDs.
6. If evidence warrants it, request a Promotion Gate evaluation.
7. Produce a proposal referencing run IDs and promotion ticket.

## Execution boundary

Hermes does not start `paper`/`testnet`, create Human Approval Receipts, reset the circuit breaker, or read broker secrets.

When future Agent-triggered Paper/Testnet dispatch is connected, it must go through the Action Gateway. LLM confidence language is never an authorization signal.
