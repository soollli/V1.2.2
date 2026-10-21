# XQuant Beginner 1–9 → Quant MVP V0.5 映射

这份文件记录“学到什么、哪些直接融合、哪些不能机械照搬”。

## 总纲：做 → 看 → 疑

- 做：规则、参数、阈值、时间范围、成本口径都显式。
- 看：收益必须有 benchmark；同时看回撤、收益结构、交易质量和执行成本。
- 疑：漂亮回测只是开始；必须做 OOS、Walk-forward、参数稳定性和受控实验。

## 逐章映射

1. 跑通第一个策略：保留一个最小可工作的策略闭环；冠军参数不能直接当答案。
2. 标的池：先定义 Universe，再研究选择逻辑。Crypto 版先用高流动性币组成小 Universe，而不是全市场乱扫。
3. 买多少：仓位/风险分配是独立于信号的模块；后续可加波动率目标仓位和风险预算。
4. 何时买卖：规则与信号分离；手续费/滑点不是事后备注，而是策略的一部分。
5. 判断好坏：任何策略都要对比简单 benchmark；网页增加净值、回撤、Rolling 指标与多维指标卡。
6. 防过拟合：参数稳定性优先于单点最优；已有 OOS scan + Walk-forward；后续再补 Time-Series CV 和 rule-burden 测试。
7. 执行交易：回测与模拟成交存在执行落差；V0.5 成交日志记录 expected price / realized slippage，诊断页优先查执行。
8. 监控诊断迭代：先执行、再市场 regime、最后策略；网页独立 DIAGNOSTICS 页照此顺序组织。每次修改前先写 hypothesis + acceptance criteria。
9. 因子研究：因子必须在多资产截面上用 Spearman IC 评估。V0.5 加入 BTC/ETH/BNB/SOL/XRP/ADA 的 Momentum/RAM/Volatility/Reversal 因子实验。

## 不机械照搬 ETF/股票的部分

- 年化：Crypto 24/7，使用 365 天基础，不使用股票 252 交易日默认值。
- 整数股：Crypto 可小数下单，真正要处理的是 minQty / stepSize / minNotional。
- 再平衡“5/10/21/63 交易日”：不能直接照搬到 1m/1h Crypto；V0.5 明确把监控阈值写成 bars，并要求 config 中说明周期。
- 因子 Universe：ETF 的 25 资产例子不直接照搬；第一阶段用 6 个流动性较高的币验证工程流程，扩大 Universe 前先解决上市历史/幸存者偏差/稳定币/流动性筛选。
- IC 阈值：|IC| 0.03/0.05/0.1 只作为研究经验尺，不作为自动交易开关。

## V0.6 候选

- 时间序列交叉验证（多折，保持时间顺序）
- Rule-burden / complexity penalty：规则每增加一条都要证明 OOS 改善
- Execution reconciliation：理论信号/预期成交 vs 实际成交逐笔对账
- 市场 regime：高/低波动、趋势/震荡的独立分类
- Factor group analysis：高波动组 vs 低波动组 IC
- Universe 筛选：流动性、上市时间、缺失值、稳定币和异常币过滤
- 波动率过滤策略 wrapper：因子研究发现 → 策略补丁 → 对照回测
