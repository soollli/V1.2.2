# V1.2.1 Research & Execution Integrity

This release intentionally pauses new engine integrations and fixes evidence quality first.

## P0 changes

- Binance research history is paginated beyond the 1000-row REST page limit.
- Market history cache is merged, deduplicated, gap-checked and fingerprinted.
- Native backtests default to signal-at-close -> fill-at-next-open.
- Strategy benchmark windows are aligned after indicator warm-up.
- Paper realized PnL uses fee-inclusive cost basis on both sides.
- Portfolio state writes are atomic.
- Qlib time splits use purge + embargo around future-label boundaries.
- Qlib hyperparameters are selected on Validation; Test remains untouched.
- Qlib current inference is separated from labeled historical Test ranking.
- Every research command archives an immutable run bundle with config/environment/data fingerprint.
- Testnet orders use unique client order IDs; timeout/`-1007` resolves by order query, never blind resubmission.
- Testnet account reconciliation blocks automation when exchange position and local cost basis disagree.
- Testnet filters use MARKET_LOT_SIZE/LOT_SIZE and NOTIONAL/MIN_NOTIONAL checks.
- Binance FULL fills parse quote/base commissions and preserve unconverted commission metadata.
- Dashboard is loopback-only until authenticated remote access exists.
- Project runtime is pinned to Python 3.12 (`.python-version`) for Qlib compatibility.

## Research run layout

```text
research/runs/<run_id>/
  manifest.json
  config.json
  data_manifest.json
  environment.json
  report.json
```

The `research/results/latest_*.json` files are convenience pointers only.

## Promotion rule

No factor/model/parameter set is trade permission. Promotion remains:

```text
reproducible
-> no known leakage
-> benchmark
-> OOS
-> walk-forward
-> cost/drawdown/stability
-> paper
-> testnet
```
