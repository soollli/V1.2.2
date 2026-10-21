# Fusion Decision V1.2 — Qlib as ML Candidate Engine

## Decision

Qlib is **not** allowed to replace Native Research validation. It is integrated as a separate ML candidate engine.

## Why

Qlib is strongest at Dataset / Forecast Model / experiment workflows. The terminal already has deterministic benchmark, OOS parameter scan, walk-forward, drawdown and execution-cost discipline. Those controls should remain independent of the model framework being evaluated.

## Boundary

```text
Canonical DataFrame panel -> Qlib Forecast Model -> prediction evidence
                                               |
                                               v
                                       CANDIDATE_ONLY
                                               |
                                               v
Native strategy specification -> OOS / walk-forward / costs -> Paper
```

## V1.2 implementation

- `QlibResearchAdapter`
- actual `qlib.contrib.model.linear.LinearModel` runtime when pyqlib is installed
- custom Dataset-compatible DataFrame wrapper implementing Qlib's `prepare()` contract
- chronological Train / Valid / Test segmentation
- cross-sectional Test IC / ICIR
- top-bottom forward spread
- no order placement
- no live money
- no Qlib `.bin` lock-in yet

## Explicitly deferred

- Alpha158 / Alpha360 over Qlib binary store
- Qlib PortAnaRecord as production portfolio validator
- RD-Agent autonomous factor mining
- automatic promotion from Qlib score to Paper

These come only after the current candidate boundary is proven stable.
