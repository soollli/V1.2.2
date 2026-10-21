# Hermes integration — AI Quant Terminal Core V1.2.2

This project is deliberately independent from Hermes. Hermes/Agnes may research and diagnose through a restricted tool surface, but the deterministic trading engine remains a separate operator-owned process.

## Required Agent entrypoint

Use:

```bash
python scripts/agent_cli.py <allowed-command> [args]
```

Do **not** give Hermes unrestricted shell for this project. Machine-readable policy: `hermes/TOOL_POLICY.json`.

Examples:

```bash
python scripts/agent_cli.py status --mode paper
python scripts/agent_cli.py snapshot --mode paper
python scripts/agent_cli.py research --bars 5000
python scripts/agent_cli.py factors --bars 5000
python scripts/agent_cli.py capm --bars 5000
python scripts/agent_cli.py portfolio --bars 5000
python scripts/agent_cli.py theories --bars 5000
python scripts/agent_cli.py walkforward --bars 5000
python scripts/agent_cli.py skills
python scripts/agent_cli.py agent-policy
python scripts/agent_cli.py circuit-status
```

## Operator-only process control

A human/operator starts and stops engines outside the Agent tool surface:

```bash
python run.py paper
python run.py testnet
python run.py terminal --mode paper
```

Human approvals and circuit reset/halt are also operator-only.

## Safety rules

- Never expose raw `.env` or Binance credentials to Hermes/Agnes.
- Never add or enable a Binance production/live-money broker in this alpha.
- Promotion tickets come from immutable research evidence; LLM confidence is irrelevant.
- Human approval receipts are one-time and payload-bound.
- Do not change strategy/risk parameters while an engine is running.
- Preserve mode-separated states and inspect reconciliation before Testnet execution.
