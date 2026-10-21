from __future__ import annotations
import csv
from datetime import datetime, timezone
import time

from .brokers import Fill
from .config import Settings
from .core.registry import AdapterRegistry
from .monitor import mode_path
from .process_lock import ProcessLock
from .risk import RiskManager
from .state import PortfolioState
from .strategy import EmaRsiStrategy


class TradingEngine:
    def __init__(self, settings: Settings, force_mode: str | None = None):
        self.s = settings
        self.mode = force_mode or settings.broker["mode"]
        self.registry = AdapterRegistry(settings)
        use_testnet_data = self.mode == "binance_testnet"
        self.market = self.registry.data(use_testnet=use_testnet_data)
        self.strategy = EmaRsiStrategy(**{k: v for k, v in settings.strategy.items() if k != "name"})
        self.risk = RiskManager(settings.risk)

        self.state_path = mode_path(settings, "state_file", self.mode)
        self.trades_path = mode_path(settings, "trades_file", self.mode)
        self.events_path = mode_path(settings, "events_file", self.mode)
        self.lock_path = settings.root / "data" / f"engine_{self.mode}.pid"
        self.state = PortfolioState.load(self.state_path, settings.broker["initial_quote_balance"])

        self.broker = self.registry.execution(self.mode)

    def log_event(self, text: str):
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        line = f"{datetime.now(timezone.utc).isoformat()} | {text}"
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(line)

    def log_fill(self, fill: Fill, reason: str, expected_price: float):
        self.trades_path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.trades_path.exists()
        slippage_bps = ((fill.price / expected_price) - 1.0) * 10000.0 if expected_price else 0.0
        if fill.side == "SELL":
            slippage_bps = -slippage_bps
        with self.trades_path.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["time_utc", "mode", "side", "price", "expected_price", "slippage_bps_realized", "base_qty", "quote_qty", "fee_quote", "reason", "order_id"])
            w.writerow([
                datetime.now(timezone.utc).isoformat(), self.mode, fill.side, fill.price,
                expected_price, slippage_bps, fill.base_qty, fill.quote_qty, fill.fee_quote, reason, fill.order_id
            ])

    def apply_fill(self, fill: Fill):
        st = self.state
        if fill.side == "BUY":
            old_qty = st.base_qty
            old_price_cost = st.avg_entry * old_qty
            new_price_cost = fill.price * fill.base_qty
            st.base_qty += fill.base_qty
            st.avg_entry = (old_price_cost + new_price_cost) / st.base_qty if st.base_qty else 0.0
            # Paper Fill.quote_qty is total cash debited (asset spend + fee).
            # For exchange fills, normalized fee_quote is added when it is not
            # already included in quote_qty. The current testnet adapter marks
            # this explicitly in raw["fee_in_quote_qty"].
            fee_extra = 0.0 if fill.raw.get("fee_in_quote_qty") else float(fill.fee_quote)
            st.cost_basis_quote += float(fill.quote_qty) + fee_extra
            if self.mode == "paper":
                st.quote_balance -= fill.quote_qty
        else:
            pre_qty = float(st.base_qty)
            sold_qty = min(float(fill.base_qty), pre_qty)
            allocated_cost = (st.cost_basis_quote * sold_qty / pre_qty) if pre_qty > 0 else 0.0
            # SELL Fill.quote_qty is normalized net quote proceeds.
            pnl = float(fill.quote_qty) - allocated_cost
            st.realized_pnl += pnl
            st.cost_basis_quote = max(0.0, st.cost_basis_quote - allocated_cost)
            st.base_qty = max(0.0, pre_qty - sold_qty)
            if self.mode == "binance_testnet" or st.base_qty < 1e-12:
                st.base_qty = 0.0
                st.avg_entry = 0.0
                st.cost_basis_quote = 0.0
            elif st.base_qty > 0:
                # Keep avg_entry as execution-price basis for risk rules.
                st.avg_entry = st.avg_entry
            if self.mode == "paper":
                st.quote_balance += fill.quote_qty
        st.save(self.state_path)


    def reconcile_testnet_account(self, symbol: str):
        if self.mode != "binance_testnet":
            return
        balances = self.broker.account_balances(symbol)
        actual_base = float(balances["base_balance"])
        actual_quote = float(balances["quote_balance"])
        st = self.state
        st.quote_balance = actual_quote
        tolerance = max(1e-8, abs(actual_base) * 0.001, abs(st.base_qty) * 0.001)
        mismatch = abs(actual_base - st.base_qty) > tolerance
        if mismatch:
            previous = st.base_qty
            st.base_qty = actual_base
            if actual_base <= tolerance:
                st.base_qty = 0.0
                st.avg_entry = 0.0
                st.cost_basis_quote = 0.0
                st.reconciliation_required = False
                st.reconciliation_note = "position_flat_after_account_sync"
            else:
                # Cost basis cannot be inferred safely from a balance snapshot.
                st.avg_entry = 0.0
                st.cost_basis_quote = 0.0
                st.reconciliation_required = True
                st.reconciliation_note = f"base_balance_mismatch local={previous:.12g} exchange={actual_base:.12g}; manual cost-basis reconciliation required"
        elif actual_base > tolerance and st.avg_entry <= 0:
            st.reconciliation_required = True
            st.reconciliation_note = "exchange_position_exists_without_local_cost_basis"
        else:
            st.reconciliation_required = False
            st.reconciliation_note = "account_balances_match_local_position"
        st.last_account_sync_utc = datetime.now(timezone.utc).isoformat()
        st.save(self.state_path)

    def one_cycle(self):
        m = self.s.market
        if self.mode == "binance_testnet":
            self.reconcile_testnet_account(m["symbol"])
        df = self.market.klines(m["symbol"], m["interval"], int(m["history_bars"]))
        closed = df.iloc[:-1].copy() if len(df) > 1 else df
        if closed.empty:
            raise RuntimeError("No closed candles returned")
        result = self.strategy.evaluate(closed)
        bar_time = result.timestamp
        if bar_time == self.state.last_bar_time:
            return

        price = float(closed.iloc[-1]["close"])
        now = datetime.now(timezone.utc).isoformat()
        self.state.last_bar_time = bar_time
        self.state.last_price = price
        self.state.last_signal = result.signal.value
        self.state.last_reason = result.reason
        self.state.last_update_utc = now
        self.log_event(f"bar={bar_time} price={price:.2f} signal={result.signal.value} reason={result.reason}")

        if self.state.reconciliation_required:
            self.state.save(self.state_path)
            self.log_event(f"NO_ORDER reconciliation_required {self.state.reconciliation_note}")
            return

        decision = self.risk.stop_or_take_profit(self.state, price)
        if decision is None:
            decision = self.risk.on_signal(result.signal.value, self.state, price)

        if decision.allowed and decision.action == "BUY":
            fill = self.broker.market_buy(m["symbol"], decision.quote_amount, price)
            self.apply_fill(fill)
            self.log_fill(fill, decision.reason, price)
            self.log_event(f"FILLED BUY qty={fill.base_qty:.8f} px={fill.price:.2f}")
        elif decision.allowed and decision.action == "SELL":
            fill = self.broker.market_sell(m["symbol"], decision.base_qty, price)
            self.apply_fill(fill)
            self.log_fill(fill, decision.reason, price)
            self.log_event(f"FILLED SELL qty={fill.base_qty:.8f} px={fill.price:.2f}")
        else:
            self.state.save(self.state_path)
            self.log_event(f"NO_ORDER {decision.reason}")

    def run_forever(self):
        with ProcessLock(self.lock_path):
            self.log_event(f"START mode={self.mode} symbol={self.s.market['symbol']} interval={self.s.market['interval']}")
            while True:
                try:
                    self.one_cycle()
                except KeyboardInterrupt:
                    self.log_event("STOP keyboard_interrupt")
                    break
                except Exception as e:
                    self.log_event(f"ERROR {type(e).__name__}: {e}")
                time.sleep(float(self.s.market["poll_seconds"]))
