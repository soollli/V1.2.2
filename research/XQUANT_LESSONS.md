# XQuant Beginner -> Crypto Quant MVP mapping

## Directly adopted
- Do -> Measure -> Doubt as the research loop.
- Benchmark first; raw return alone is not enough.
- Multi-dimensional evaluation: return, drawdown, recovery/underwater time, downside risk, win/loss quality.
- Parameter sensitivity: prefer broad stable regions to one sharp optimum.
- Train/test separation and walk-forward checks.
- Explicit execution gap: fees/slippage/constraints belong in research.
- Monitoring/diagnosis/iteration with pre-declared acceptance criteria.
- Agent research discipline and reproducible experiment logs.

## Adapted for crypto
- 24/7 market -> 365-day annualization basis, not 252 trading days.
- Spot crypto supports fractional quantities; stock integer-share rounding is not copied literally.
- Exchange minQty/minNotional and lot-size filters matter instead.
- Current MVP is Spot only, so futures funding/liquidation are intentionally absent.
- Universe selection will later use crypto-specific liquidity/volume/listing-age filters rather than GDP/ETF logic.

## Deferred to next layer
- Multi-symbol universe ranking.
- Cross-sectional factor IC/ICIR pipeline across BTC/ETH/large-cap crypto.
- Regime-aware strategy switching.
- Automated research scheduler.
