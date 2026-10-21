# AI Quant Terminal Core V1.2.2 — Agent Safety Alpha

个人自用的 **AI-native Bloomberg-like Quant Terminal + Quant Research + Paper/Testnet**。

V1.2.2 在 V1.2.1 的研究/执行完整性基础上，新增 Agent Safety Plane：Skill Registry、Autonomy Policy、Promotion Gate、一次性 Human Approval Receipt、Circuit Breaker、Decision Receipt、restricted Agent CLI 与交易密钥隔离。

## 锁定架构

```text
Web Terminal / Shell
        |
AI / Hermes
        |
Data Fabric ------------------------------+
  |                                       |
Binance market truth + OpenBB research    |
  |                                       |
  +------ Native Research Validator <-----+---- Qlib ML Candidate Engine
  |          |                                  |
  |          +-- benchmark / OOS                +-- purged train/valid/test
  |          +-- walk-forward                   +-- validation model selection
  |          +-- costs / drawdown               +-- current inference
  |                                             |
  +---------------- Portfolio/Ledger ------------+
                         |
                 Native Execution
                 Paper / Binance Testnet
                 future Freqtrade/Nautilus sidecars
```

## V1.2.2：Agent Safety Plane

V1.2.2 把 xFutureTrade/Robinhood Agents 的关键安全思想转成自己的确定性边界，但不复制它们的产品代码：

```text
Agnes / Hermes
     |
     | restricted skills only
     v
Skill Registry
     |
Promotion Gate ---- immutable research run IDs
     |
Action Gateway ---- autonomy / budget / circuit breaker
     |
Human Approval Receipt (operator-only, one-time, short-lived)
     |
Deterministic Trading Engine
     |
Paper / Binance Spot Testnet
```

默认 `agent.autonomy_level: propose`，因此 Agent 可以读取、研究、提出策略候选，但不能自动 Paper/Testnet。当前 **没有 live-money command**。

关键命令：

```bash
python run.py skills
python run.py agent-policy
python run.py circuit-status
```

Hermes/Agnes 应使用受限入口：

```bash
python scripts/agent_cli.py snapshot --mode paper
python scripts/agent_cli.py research --bars 5000
```

`hermes/TOOL_POLICY.json` 明确禁止 Agent 使用：`paper`、`testnet`、`human-approve`、`circuit-halt/reset` 等 operator-only 控制。**如果给 Hermes 任意 shell 权限，这个隔离可以被绕过，所以生产式部署必须只暴露受限 Tool/MCP surface。**

### Promotion Gate

研究结果不能靠 LLM 自述晋级。至少提供 immutable strategy + walk-forward run IDs：

```bash
python run.py promotion-check \
  --run-id <strategy_run_id> \
  --run-id <walkforward_run_id>
```

通过后得到短时效 `promotion_ticket`。它仍然不是订单。

### Human Approval Receipt

默认 trade approval 为 ON。人类审批是独立 operator-only 步骤，并绑定：skill、mode、promotion ticket、完整 payload hash，且只能使用一次：

```bash
python run.py human-approve \
  --skill execution.paper \
  --mode paper \
  --promotion-ticket <ticket_id> \
  --side BUY \
  --quote-amount 25
```

然后 Gateway 只做授权检查，不直接下单：

```bash
python run.py gateway-check \
  --skill execution.paper \
  --mode paper \
  --promotion-ticket <ticket_id> \
  --approval-id <approval_id> \
  --side BUY \
  --quote-amount 25
```

V1.2.2 的 Gateway **故意不 dispatch order**。下一阶段若连接 Agent 自动 Paper，必须把授权与实际 dispatch 合并成原子路径，避免 TOCTOU。

### Circuit Breaker

Operator 可以立即阻断所有 Agent 市场变更请求：

```bash
python run.py circuit-halt --reason "manual risk halt"
python run.py circuit-status
python run.py circuit-reset --reason "review complete"
```

这些控制不属于 Agent Skill Registry。

不可改变的职责：

- **Binance**：当前 Crypto 交易与执行真源。
- **OpenBB**：研究数据 Fabric，不下单。
- **Qlib**：产生 ML candidate，不下单、不自动晋级。
- **Native Research**：独立验证 Gate。
- **Hermes**：研究、诊断、编排；不维护分钟级订单/仓位状态。
- 当前没有 live-money command。

## 运行环境

项目正式锁定 **Python 3.12**。`.python-version` 已包含 `3.12`。这是为了让 Core/OpenBB/Qlib 共用一个稳定环境；`pyqlib 0.9.7` 有 CPython 3.12 wheel。

macOS 推荐：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
```

验证：

```bash
pytest -q
python scripts/smoke_local.py
python run.py doctor --mode paper
```

如果 `doctor` 显示 Python 不是 3.12，请重新创建 venv，不要复用系统 Python 3.13 环境。

## Paper + Web Terminal

终端 1：

```bash
python run.py paper
```

终端 2：

```bash
python run.py terminal --mode paper
```

打开：

```text
http://127.0.0.1:8765
```

V1.2.2 Dashboard **只允许 loopback**。`0.0.0.0` 等远程绑定会被拒绝，直到以后加入认证。

页面：`TRADE / RESEARCH / DIAGNOSTICS / SYSTEM`。

> Lightweight Charts 仍使用固定版本 CDN，并保留 native Canvas fallback。构建环境无法下载 vendor 文件，所以本轮没有伪装成“已本地化”；断网时仍可用 Canvas fallback。

## Binance 历史数据：不再卡 1000 bars

Binance 单页最多 1000 根 K 线，但 V1.2.2 的 `BinanceDataAdapter.history()` 会自动使用 `endTime` 向历史分页回补。

因此：

```bash
python run.py research --bars 5000
python run.py factors --bars 5000
python run.py qlib-ml --bars 5000
```

不再被静默截断为 1000。

历史数据同时执行：

- closed-bar 筛选
- open_time 去重
- 时间单调检查
- 固定周期 gap 检查
- 本地 `data/cache/market/*.csv.gz` 缓存
- SHA256 数据指纹

研究层如果发现缺口/重复，不会默默继续算结果。

## Native Backtest：默认 NEXT_OPEN

旧版近似：

```text
bar t close -> signal -> same close fill
```

V1.2.2 默认：

```text
bar t close -> signal -> bar t+1 open fill -> slippage/fee
```

`same_close` 只保留给明确的 optimistic diagnostic/parity test。

Benchmark 也会从策略真实 equity curve 开始的时间计算，不再把 indicator warm-up 期间偷偷算给 Buy & Hold。

## Paper PnL 修复

状态现在同时维护：

```text
avg_entry           # 执行价基准，供简单止损/止盈
cost_basis_quote    # 含买入手续费的会计成本
```

SELL realized PnL 使用净卖出 proceeds 减分摊成本，所以 BUY + SELL 两边手续费都进入 realized PnL。

state 保存改为临时文件 + `os.replace` 原子写入，降低崩溃产生半截 JSON 的风险。

## Qlib：Purged Validation

可选安装：

```bash
pip install -r requirements-qlib.txt
python run.py qlib-check
```

建议第一次真实研究：

```bash
python run.py qlib-ml --bars 5000
```

V1.2.2 的时间流程：

```text
TRAIN
  ↓ purge(forward_bars)
VALID
  ↓ purge(forward_bars)
TEST
```

默认还有 1 bar embargo。

Qlib Ridge/Lasso：

1. 只用 Train 拟合候选 alpha；
2. 在 Validation 比较 cross-sectional IC / MSE；
3. 选出 alpha；
4. 用 Train + Valid 重训；
5. Test 只做最终一次评估。

Feature preprocessing 的 winsorization / standardization 统计量也只从 Train 拟合。

报告明确区分：

```text
latest_labeled_test
    有真实 future return，用于验证

current_inference
    最新 feature-only score，没有未来 label
```

Current inference 绝不显示伪造 realized future return。

## Factor Lab

```bash
python run.py factors --bars 5000
```

仍使用 cross-sectional Spearman IC。当前默认 universe 只有 6 个资产，因此 **总体 IC 是探索性结果**。

V1.2.2 将 high/low-vol grouped IC 的每组最低资产数提高到 4；如果样本不足就不报告，而不是用 2 vs 2 / 3 vs 3 生成看似极端的相关性。

## Portfolio 与 CAPM 研究

```bash
python run.py capm --bars 5000
python run.py portfolio --bars 5000
python run.py theories --bars 5000
```

`capm`：单因子 CAPM / SML 诊断（market 代理默认等权 universe 指数，`portfolio_research.market_model: btc` 可切 BTC）。输出每资产 beta / alpha（t 检验）/ R²，以及 two-pass SML 拟合（年化 slope、intercept、R²）。判定阈值：`capm_alpha_t: 2.0`、`capm_min_sml_r2: 0.6`。

`theories`（`src/theory_backtests.py`，skill `research.theories`）：四大理论回测电池，同一 universe、同成本模型（fee 0.1% + slippage 2bps，next-open 约定，信号在 t、仓位 t+1 生效，无 lookahead）：

1. **CAPM（资本资产定价模型）**：复用 two-pass SML + beta 三分位 long-short 回测（含成本门槛）。
2. **弱式市场有效性（EMH）**：1h/1d 收益 Ljung-Box 自相关、k=2/5/10 方差比、lag-1/24/168 动量 t 统计、GARCH(1,1) 常方差拒绝（确定性 grid + Nelder-Mead MLE，无 RNG、无 OOS 泄漏）。
3. **期权定价假设（Black-Scholes）**：本项目无期权行情，测的是模型**假设**——逐资产日频对数收益 Jarque-Bera 正态性 + GARCH 常方差拒绝。
4. **无套利（统计套利）**：配置协整对（滚动 hedge beta + ADF 5% + AR(1) 半衰期）+ z-score 区间带策略回测（成本门槛：net ≤ 0 即无可用边际）。

全部确定性（仅 `generated_utc` 时间戳），走 immutable run archive + Promotion Gate，只产研究证据，不触发执行。配置在 `config.yaml` 的 `theory_tests:` 段。

`portfolio`：walk-forward 组合候选（`equal_weight` / `min_variance` / `mvo_shrinkage` / `risk_parity`）：

- 协方差用 OAS（Ledoit-Wolf）收缩，估计只用 expanding train 窗口，**无 lookahead**
- 每个 fold 调仓一次，next-open 风格成交 + 0.1% 手续费 + 2bps 滑点
- 基线：等权组合（同调仓频率）+ 各资产 buy & hold（gross）
- 报告含 OOS 正收益 fold 占比、换手率、成本、回撤、Sharpe（365 天年化）

配置全部在 `config.yaml` 的 `portfolio_research:` 段。结论仍是**研究证据**：6 资产 universe 属探索性结果，任何候选要进执行必须走 Promotion Gate（immutable run ID）+ 人类审批。

## 不可变 Research Run

每次以下命令：

```text
research
scan
walkforward
factors
capm
portfolio
theories
qlib-ml
```

都会生成唯一 `run_id`：

```text
research/runs/<run_id>/
  manifest.json
  config.json
  data_manifest.json
  environment.json
  report.json
```

记录：

- project version
- 完整 config hash
- data fingerprint
- Python / package versions
- report hash

`research/results/latest_*.json` 只是 Web Terminal 的快捷指针，不是唯一证据。

## OpenBB V5

```bash
pip install -r requirements-openbb.txt
python run.py openbb-check
```

`FRED endpoints 需要自己的 FRED key。V1.2.2 不再让所有命令自动加载项目 `.env`，因此 OpenBB key 建议按 OpenBB V5 方式放在：

```text
~/.openbb_platform/.env
```

项目提供 `openbb.env.example` 作为示例。CBOE/Nasdaq/SEC 当前适配路径不需要 FRED key。

OpenBB 仍然只做 Research Data Fabric，不作为 Binance execution price truth。

## Binance Spot Testnet Integrity

```bash
cp .env.example .env
```

只填写 Testnet key：

```text
BINANCE_TESTNET_API_KEY=
BINANCE_TESTNET_API_SECRET=
```

然后：

```bash
python run.py testnet
```

V1.2.2 新保护：

- 每笔订单唯一 `newClientOrderId`
- 网络 timeout / Binance `-1007` 后查询同一个 clientOrderId
- **不会因为 response 不确定就自动重发第二笔订单**
- MARKET_LOT_SIZE / LOT_SIZE 检查
- NOTIONAL / MIN_NOTIONAL 检查
- FULL fill commission 解析
- base/quote commission 归一化
- 其它 fee asset 保留为 `unconverted_commissions`
- 定期读取 Testnet account balance 与本地 state 对账
- 交易所持仓和本地 cost basis 不一致时设置 `reconciliation_required=true`
- reconciliation_required 时自动停止新订单

当前 stop-loss / take-profit 仍是 **CLIENT-SIDE**。程序停止时保护逻辑也停止；这不是交易所原生保护单。

## 当前真实开源融合状态

看：

```bash
python run.py capabilities
```

或 `docs/OPEN_SOURCE_FUSION_STATUS.md`。

当前：

```text
Lightweight Charts  ACTIVE
OpenBB              IMPLEMENTED OPTIONAL
Qlib                IMPLEMENTED OPTIONAL
Binance Native      ACTIVE
Native Research     ACTIVE
Native Execution    ACTIVE
Freqtrade           SLOT
NautilusTrader      SLOT
rotki                FUTURE
```

## Promotion Gate

长期目标仍是：

```text
reproducible -> no known leakage -> benchmark -> OOS -> walk-forward
-> cost -> drawdown -> stability -> Paper -> Testnet
```

V1.2.2 当前已机器化其中一部分：immutable run evidence、next-open、strategy excess/DD/order count、walk-forward fold/OOS ratio、parameter variation，以及可选 Qlib test IC。它还**不是最终 production promotion policy**。

## 下一阶段

暂不接 Freqtrade。下一轮建议回到研究与组合构建：

- parameter neighborhood plateau score
- nested walk-forward parameter selection
- block-bootstrap / non-overlap IC confidence
- Qlib score -> Top-N Portfolio Candidate backtester
- ~~risk parity / equal weight portfolio construction~~ ✅ `run.py portfolio`（EW / min-var / MVO-shrinkage / risk-parity，OAS 协方差，walk-forward + next-open 成本）
- ~~turnover/cost benchmark~~ ✅ 同命令：换手率、成本 quote、gross/net 对照
- CAPM / SML 单因子诊断 ✅ `run.py capm`
- 将 Action Gateway 授权与未来 Agent Paper dispatch 做成原子路径

这些通过以后，再进入 Freqtrade dry-run sidecar。
