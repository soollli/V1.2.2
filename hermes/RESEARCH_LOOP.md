# Hermes Research Loop — V0.5

Hermes 只做研究与诊断，不维持交易状态。

## Daily / on demand

1. `python run.py status --mode paper`
2. 先读 Execution：错误、滑点、费用、重复进程。
3. 再读 Market regime。
4. 最后读 Strategy 指标。
5. 发现问题先形成 hypothesis 和 acceptance criteria，不准先改参数再解释。

## Research batch

```bash
python run.py research --bars 1000
python run.py scan --bars 1000
python run.py walkforward --bars 1000
python run.py factors --bars 1000
```

然后读取 `research/results/*.json`。

禁止：只根据训练集第一名自动更新生产/模拟交易策略。


## Qlib candidate loop (V1.2)

1. `python run.py qlib-check`
2. `python run.py qlib-ml --bars 1000`
3. Read `research/results/latest_qlib_ml_report.json`.
4. Treat the result as `CANDIDATE_ONLY`.
5. Do **not** change Paper/Testnet behavior from a Qlib score alone.
6. Convert a useful score into an explicit portfolio/rebalance rule.
7. Run Native benchmark/OOS/walk-forward/execution-cost validation.
8. Only a candidate that survives the native gate can advance toward Paper.
