# Agentic Trading Benchmark — xFutureTrade & Robinhood Agents

Reviewed: 2026-10-15.

## Source-derived observations

### Robinhood (official public documentation)

Robinhood currently documents:

- built-in and external agents powered by third-party LLMs;
- a dedicated Agentic account for Agent trading;
- trade approvals enabled by default for built-in Agents;
- external Agent access through Trading MCP;
- equities/options/crypto Agent trading;
- configurable skills;
- a newer Cortex architecture using one strong model, one prompt and rich tools rather than ~10 specialist agents;
- coming Agent Loops for scheduled/continuous operation.

Official sources used during review:

- https://robinhood.com/us/en/support/articles/setting-up-an-agent/
- https://robinhood.com/us/en/support/articles/trading-with-your-agent/
- https://robinhood.com/us/en/support/articles/robinhood-agents-overview/
- https://robinhood.com/us/en/careers/blog/loop-stays-dumb-so-the-model-can-be-smart/
- https://robinhood.com/newsroom/robinhood-is-now-open-to-agents/

### xFutureTrade (public website)

Public pages inspected include the main site, `/safetrade`, `/finn`, `/skills`, `/membership`, and `/home`. The site presents itself as an Agentic trading OS with Canvas/skills, research-to-execution workflows, broker/data integrations and a Finn/A2M risk-control concept.

Important: integration counts, infrastructure claims, strategy performance numbers and partnership branding visible on public marketing pages were **not independently verified**. They are treated as product claims, not evidence of realized execution quality or strategy edge.

## Our architectural decisions (inference/design, not source claims)

1. **Do not copy a multi-Agent swarm.** Follow the Robinhood Cortex lesson: one capable model/loop plus deterministic tools/skills.
2. **Adopt xFuture-like skill composition, not xFuture code.** Macro, factor, Qlib, risk and execution remain modular deterministic capabilities.
3. **Risk control plane sits between Agent and market.** Promotion + budget + circuit + approval are independent of LLM output.
4. **Separate capital boundary is desirable.** Current project isolates paper/testnet states, but does not yet implement a broker-side dedicated Agent account.
5. **Agent tool access must be restricted.** The Agent must not receive unrestricted shell or operator controls.
6. **Decision receipts are mandatory.** Every authorization decision captures request payload hash, policy, skill, reasons and evidence.
