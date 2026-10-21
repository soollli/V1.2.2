from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import pandas as pd

from .brokers import PaperBroker
from .risk import RiskManager
from .state import PortfolioState
from .strategy import EmaRsiStrategy, rsi


@dataclass
class BacktestResult:
    start_equity: float
    end_equity: float
    return_pct: float
    trades: int
    realized_pnl: float
    fees_paid: float = 0.0
    turnover_quote: float = 0.0
    fill_mode: str = "next_open"
    equity_curve: pd.DataFrame = field(default_factory=pd.DataFrame)
    round_trips: list[dict[str, Any]] = field(default_factory=list)


def _apply_buy(st: PortfolioState, fill) -> None:
    old_qty = float(st.base_qty)
    old_price_cost = float(st.avg_entry) * old_qty
    st.base_qty = old_qty + float(fill.base_qty)
    st.avg_entry = (old_price_cost + float(fill.price) * float(fill.base_qty)) / st.base_qty if st.base_qty else 0.0
    # Paper quote_qty is the full cash debit and therefore already includes the buy fee.
    st.cost_basis_quote += float(fill.quote_qty)
    st.quote_balance -= float(fill.quote_qty)


def _apply_sell(st: PortfolioState, fill) -> float:
    pre_qty = float(st.base_qty)
    sold = min(float(fill.base_qty), pre_qty)
    allocated_cost = st.cost_basis_quote * sold / pre_qty if pre_qty > 0 else 0.0
    pnl = float(fill.quote_qty) - allocated_cost
    st.realized_pnl += pnl
    st.cost_basis_quote = max(0.0, st.cost_basis_quote - allocated_cost)
    st.quote_balance += float(fill.quote_qty)
    st.base_qty = max(0.0, pre_qty - sold)
    if st.base_qty < 1e-12:
        st.base_qty = 0.0
        st.avg_entry = 0.0
        st.cost_basis_quote = 0.0
    return pnl


def run_backtest(
    df: pd.DataFrame,
    strategy_cfg: dict,
    risk_cfg: dict,
    initial_quote: float = 10000.0,
    start_index: int | None = None,
    fill_mode: str = "next_open",
):
    """Run the deterministic native backtest.

    ``next_open`` is the default research mode: a signal only exists after bar t
    closes, therefore its order is filled at bar t+1 open (plus configured
    slippage). ``same_close`` remains available only as an explicitly optimistic
    diagnostic for parity checks with older reports.
    """
    if df is None or len(df) == 0:
        raise ValueError("backtest requires non-empty dataframe")
    if fill_mode not in {"next_open", "same_close"}:
        raise ValueError("fill_mode must be next_open or same_close")

    strategy = EmaRsiStrategy(**{k: v for k, v in strategy_cfg.items() if k != "name"})
    risk = RiskManager(risk_cfg)
    broker = PaperBroker(risk_cfg["fee_rate"], risk_cfg["slippage_bps"])
    st = PortfolioState(quote_balance=initial_quote)
    trades = 0
    fees_paid = 0.0
    turnover_quote = 0.0
    equity_rows: list[dict[str, Any]] = []
    round_trips: list[dict[str, Any]] = []
    open_trade: dict[str, Any] | None = None
    pending: dict[str, Any] | None = None

    d = df.copy().reset_index(drop=True)
    d["ema_fast"] = d["close"].ewm(span=strategy.fast, adjust=False).mean()
    d["ema_slow"] = d["close"].ewm(span=strategy.slow, adjust=False).mean()
    d["rsi"] = rsi(d["close"], strategy.rsi_period)
    d["cross_up"] = (d["ema_fast"].shift(1) <= d["ema_slow"].shift(1)) & (d["ema_fast"] > d["ema_slow"])
    d["cross_down"] = (d["ema_fast"].shift(1) >= d["ema_slow"].shift(1)) & (d["ema_fast"] < d["ema_slow"])

    min_bars = max(int(strategy_cfg["slow_ema"]) + 3, int(strategy_cfg["rsi_period"]) + 3)
    begin = max(min_bars, int(start_index or 0))
    if begin >= len(d):
        raise ValueError(f"not enough bars: begin={begin}, bars={len(d)}")

    def execute(decision, execution_price: float, fill_time: Any, signal_price: float, signal_time: Any):
        nonlocal trades, fees_paid, turnover_quote, open_trade
        if decision.allowed and decision.action == "BUY":
            fill = broker.market_buy("SIM", decision.quote_amount, execution_price)
            _apply_buy(st, fill)
            fees_paid += fill.fee_quote
            turnover_quote += fill.quote_qty
            trades += 1
            open_trade = {
                "entry_time": str(fill_time),
                "signal_time": str(signal_time),
                "entry_signal_price": float(signal_price),
                "entry_market_price": float(execution_price),
                "entry_fill_price": fill.price,
                "entry_quote": fill.quote_qty,
                "entry_fee": fill.fee_quote,
                "entry_reason": decision.reason,
            }
        elif decision.allowed and decision.action == "SELL" and st.base_qty > 0:
            fill = broker.market_sell("SIM", st.base_qty, execution_price)
            _apply_sell(st, fill)
            fees_paid += fill.fee_quote
            turnover_quote += fill.quote_qty
            trades += 1
            if open_trade:
                entry_quote = float(open_trade["entry_quote"])
                rt = {
                    **open_trade,
                    "exit_time": str(fill_time),
                    "exit_signal_time": str(signal_time),
                    "exit_signal_price": float(signal_price),
                    "exit_market_price": float(execution_price),
                    "exit_fill_price": fill.price,
                    "exit_quote": fill.quote_qty,
                    "exit_fee": fill.fee_quote,
                    "exit_reason": decision.reason,
                    "net_pnl_quote": fill.quote_qty - entry_quote,
                    "return_pct": ((fill.quote_qty / entry_quote) - 1) * 100 if entry_quote else 0.0,
                }
                round_trips.append(rt)
                open_trade = None

    for i in range(begin, len(d)):
        row = d.iloc[i]

        # Execute the prior bar's decision only when this bar opens.
        if fill_mode == "next_open" and pending is not None:
            execute(
                pending["decision"],
                float(row["open"]),
                row.get("open_time", i),
                pending["signal_price"],
                pending["signal_time"],
            )
            pending = None

        close_price = float(row["close"])
        if bool(row["cross_up"]) and float(row["rsi"]) >= strategy.buy_rsi_min:
            signal = "BUY"
        elif bool(row["cross_down"]) and float(row["rsi"]) <= strategy.sell_rsi_max:
            signal = "SELL"
        else:
            signal = "HOLD"

        decision = risk.stop_or_take_profit(st, close_price) or risk.on_signal(signal, st, close_price)
        signal_time = row.get("close_time", i)
        if decision.allowed and decision.action in {"BUY", "SELL"}:
            if fill_mode == "same_close":
                execute(decision, close_price, signal_time, close_price, signal_time)
            elif i + 1 < len(d):
                pending = {
                    "decision": decision,
                    "signal_price": close_price,
                    "signal_time": signal_time,
                }

        equity = st.quote_balance + st.base_qty * close_price
        equity_rows.append({
            "time": row.get("close_time", i),
            "market_price": close_price,
            "equity": equity,
            "quote_balance": st.quote_balance,
            "base_qty": st.base_qty,
            "signal": signal,
        })

    last_price = float(d.iloc[-1]["close"])
    end_equity = st.quote_balance + st.base_qty * last_price
    curve = pd.DataFrame(equity_rows)
    if not curve.empty:
        curve["time"] = pd.to_datetime(curve["time"], utc=True, errors="coerce")

    return BacktestResult(
        start_equity=initial_quote,
        end_equity=end_equity,
        return_pct=(end_equity / initial_quote - 1) * 100,
        trades=trades,
        realized_pnl=st.realized_pnl,
        fees_paid=fees_paid,
        turnover_quote=turnover_quote,
        fill_mode=fill_mode,
        equity_curve=curve,
        round_trips=round_trips,
    )
