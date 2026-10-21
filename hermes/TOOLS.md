# Hermes Quant Tool Policy — V1.2.2

Hermes/Agnes must use the restricted wrapper, not unrestricted shell:

```bash
python scripts/agent_cli.py <command> [args]
```

Machine-readable policy: `hermes/TOOL_POLICY.json`.

## Agent-safe observation/research

- `status`
- `snapshot`
- `capabilities`
- `skills`
- `agent-policy`
- `doctor`
- `backtest`
- `research`
- `scan`
- `walkforward`
- `factors`
- `capm`
- `portfolio`
- `theories`
- `journal`
- OpenBB research commands
- Qlib research commands
- `promotion-check`
- `gateway-check`
- `circuit-status`

## Operator-only — never expose as Agent skills

- `paper`
- `testnet`
- `human-approve`
- `circuit-halt`
- `circuit-reset`
- unrestricted shell
- raw `.env` / broker credentials

A Promotion Ticket does not equal approval. Human approval is an out-of-band, one-time, payload-bound receipt. Gateway authorization still does not dispatch an order in this alpha.
