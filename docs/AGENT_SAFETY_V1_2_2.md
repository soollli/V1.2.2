# Agent Safety Plane — V1.2.2

## Goal

AI is allowed to be probabilistic. Market-state mutation must remain deterministic, bounded, auditable and revocable.

## Trust boundary

```text
Agnes/other LLM
    ↓
Hermes simple loop
    ↓
restricted deterministic Skill Registry
    ↓
Promotion Gate
    ↓
Action Gateway
    ↓
short-lived one-time Human Approval Receipt (default required)
    ↓
Trading Engine
```

The agent does **not** own Binance keys, broker state, the circuit reset control, or the human approval creator.

## Autonomy levels

| Level | Name | Intended authority |
|---:|---|---|
| 0 | observe | read snapshots only |
| 1 | research | deterministic research tools |
| 2 | propose | research-backed strategy proposals |
| 3 | paper | bounded paper execution requests after promotion + approval |
| 4 | testnet | bounded Testnet requests after promotion + approval |
| 5 | guarded_live | reserved; disabled |
| 6 | bounded_live | reserved; disabled |

Default is **propose**.

## Promotion Ticket

A promotion ticket is derived from immutable research runs, not from LLM confidence language. Current gate requires at minimum:

- strategy research run;
- next-open fill assumption;
- minimum trade count;
- drawdown threshold;
- excess-return threshold;
- walk-forward evidence;
- minimum positive OOS fold ratio;
- parameter-variation threshold;
- optional Qlib test IC check when a Qlib run is supplied.

Tickets expire. A ticket is evidence, not execution permission by itself.

## Human Approval Receipt

When trade approval is enabled, a market-mutating Agent request needs a separate approval receipt. The receipt is:

- created out-of-band by an operator-only command;
- short-lived;
- bound to exact skill/mode/promotion ticket/action payload hash;
- one-time; replay is rejected.

A boolean `human_approved=true` is intentionally insufficient.

## Circuit Breaker

`HALTED` fails closed for all Agent market mutation. A corrupt circuit state also fails closed.

Operator-only commands:

- `circuit-halt`
- `circuit-reset`

Agent may only read `circuit-status`.

## Secret isolation

`load_settings()` no longer loads project `.env`. Testnet keys are read only when the execution adapter/doctor explicitly asks for those two names. Research/Agent commands therefore do not automatically import exchange credentials into process environment.

This is defense in depth, not OS isolation. If Hermes has unrestricted shell or runs under the same unrestricted OS identity, it can bypass application policy. Production-style use must expose a restricted Tool/MCP surface instead of general shell.

## Current non-goals

- no live-money execution;
- no Agent order dispatch from Action Gateway yet;
- no broker-level dedicated Agentic Account equivalent yet;
- no cryptographic user identity/remote approval service;
- no multi-asset portfolio execution yet.
