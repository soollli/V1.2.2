# Known Limitations — V1.2.2 Agent Safety Alpha

These are deliberate, visible limits. They are not hidden behind an "integrated" label.

1. **No live-money mode.** Paper and Binance Spot Testnet only.
2. **Agent Gateway does not dispatch orders yet.** It authorizes and writes receipts. Future Agent-triggered execution must combine authorization + dispatch atomically to avoid TOCTOU.
3. **Human Approval Receipt is application-level, not OS identity.** It is one-time/payload-bound, but a process with unrestricted shell and file access can bypass policy. Hermes/Agnes must be given the restricted Tool/MCP surface, not general shell.
4. **No Robinhood-style broker-side dedicated Agentic Account.** Paper/Testnet state is separated locally; real broker-level capital isolation remains future work.
5. **Broker secrets are better isolated, not hardware-isolated.** Research/Agent commands no longer auto-load project `.env`, but a shared OS user with unrestricted environment/file access can still defeat this boundary.
6. **Client-side stop/take-profit.** If the engine stops, these protections stop. No exchange-native protective order yet.
7. **Qlib/OpenBB upstream runtime not exercised in the build container.** Adapter contracts are tested offline; install optional requirements and run `qlib-check` / `openbb-check` locally.
8. **Qlib default universe is still small (6 assets).** Cross-sectional results are exploratory. High/low-vol grouped IC is withheld when subgroup size is too small.
9. **No multi-asset execution portfolio yet.** Factor/Qlib research is multi-asset, current native execution state is still one Spot symbol at a time.
10. **Third-asset commissions are not force-converted.** If Binance charges fees in an asset other than base/quote (for example BNB), raw commission is preserved and quote PnL may be understated until a valuation layer is added.
11. **Historical cache is dependency-light CSV.GZ.** Parquet + DuckDB remains the planned storage upgrade.
12. **Lightweight Charts loads fixed v5.2.1 from CDN.** Native Canvas remains the offline fallback; local vendoring is still pending.
13. **Parameter plateau score / nested walk-forward / bootstrap IC confidence are not yet implemented.** They remain the next research-integrity workstream.
14. **Promotion Gate is intentionally conservative but incomplete.** It does not yet validate a true multi-asset portfolio candidate, block-bootstrap confidence, or broker-side execution rehearsal.
15. **No Freqtrade/Nautilus/rotki runtime integration yet.** They remain slots/future adapters.
16. **Macro vintage/revision-safe research is not implemented.** Revised FRED history must not be mistaken for point-in-time data.
17. **Dashboard is loopback-only.** Authenticated remote access is intentionally deferred.
18. **Circuit breaker is local application state.** Future sidecar execution engines need their own independent kill-switch/heartbeat integration.
