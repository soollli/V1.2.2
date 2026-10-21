from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
import hashlib
import hmac
import time
import uuid
from urllib.parse import urlencode
import requests


@dataclass
class Fill:
    side: str
    price: float
    base_qty: float
    quote_qty: float
    fee_quote: float
    order_id: str
    raw: dict


class BinanceAPIError(RuntimeError):
    def __init__(self, status: int, code: int | None, message: str, payload=None):
        super().__init__(f"Binance API error status={status} code={code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.payload = payload


class OrderStatusUnknown(RuntimeError):
    pass


class PaperBroker:
    def __init__(self, fee_rate: float = 0.001, slippage_bps: float = 2):
        self.fee_rate = fee_rate
        self.slippage = slippage_bps / 10000.0

    def market_buy(self, symbol: str, quote_amount: float, market_price: float) -> Fill:
        px = market_price * (1 + self.slippage)
        fee = quote_amount * self.fee_rate
        spend_for_asset = max(0.0, quote_amount - fee)
        qty = spend_for_asset / px
        return Fill("BUY", px, qty, quote_amount, fee, f"paper-{time.time_ns()}", {"fee_in_quote_qty": True})

    def market_sell(self, symbol: str, base_qty: float, market_price: float) -> Fill:
        px = market_price * (1 - self.slippage)
        gross = base_qty * px
        fee = gross * self.fee_rate
        net = gross - fee
        return Fill("SELL", px, base_qty, net, fee, f"paper-{time.time_ns()}", {"fee_in_quote_qty": True})


class BinanceSpotTestnetBroker:
    BASE = "https://testnet.binance.vision"

    def __init__(self, api_key: str, api_secret: str, timeout: int = 10):
        if not api_key or not api_secret:
            raise ValueError("Missing BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET")
        self.api_key = api_key
        self.api_secret = api_secret.encode()
        self.timeout = timeout
        self._symbol_cache: dict[str, dict] = {}

    def _signed(self, method: str, path: str, params: dict):
        params = dict(params)
        params["timestamp"] = int(time.time() * 1000)
        params.setdefault("recvWindow", 5000)
        query = urlencode(params)
        sig = hmac.new(self.api_secret, query.encode(), hashlib.sha256).hexdigest()
        headers = {"X-MBX-APIKEY": self.api_key}
        url = f"{self.BASE}{path}?{query}&signature={sig}"
        r = requests.request(method, url, headers=headers, timeout=self.timeout)
        if not r.ok:
            try:
                payload = r.json()
            except Exception:
                payload = {"msg": r.text}
            raise BinanceAPIError(r.status_code, payload.get("code"), payload.get("msg", r.text), payload)
        return r.json()

    def _public(self, path: str, params: dict):
        r = requests.get(f"{self.BASE}{path}", params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def _symbol_info(self, symbol: str) -> dict:
        symbol = symbol.upper()
        if symbol not in self._symbol_cache:
            info = self._public("/api/v3/exchangeInfo", {"symbol": symbol})
            if not info.get("symbols"):
                raise ValueError(f"symbol not found: {symbol}")
            self._symbol_cache[symbol] = info["symbols"][0]
        return self._symbol_cache[symbol]

    def _filter(self, symbol: str, *names: str) -> dict | None:
        filters = self._symbol_info(symbol).get("filters", [])
        for name in names:
            for f in filters:
                if f.get("filterType") == name:
                    return f
        return None

    def _lot_step(self, symbol: str):
        market_lot = self._filter(symbol, "MARKET_LOT_SIZE")
        lot = market_lot
        if not lot or Decimal(str(lot.get("stepSize", "0"))) <= 0:
            lot = self._filter(symbol, "LOT_SIZE")
        if not lot:
            raise ValueError(f"no lot-size filter for {symbol}")
        return Decimal(lot["stepSize"]), Decimal(lot["minQty"]), Decimal(lot.get("maxQty", "0"))

    def _round_qty(self, symbol: str, qty: float) -> str:
        step, min_qty, max_qty = self._lot_step(symbol)
        q = Decimal(str(qty))
        rounded = (q / step).to_integral_value(rounding=ROUND_DOWN) * step if step > 0 else q
        if rounded < min_qty:
            raise ValueError(f"quantity {rounded} below minQty {min_qty}")
        if max_qty > 0 and rounded > max_qty:
            raise ValueError(f"quantity {rounded} above maxQty {max_qty}")
        return format(rounded.normalize(), "f")

    def _validate_market_notional(self, symbol: str, quote_amount: float) -> None:
        f = self._filter(symbol, "NOTIONAL", "MIN_NOTIONAL")
        if not f:
            return
        min_notional = Decimal(str(f.get("minNotional", "0")))
        if Decimal(str(quote_amount)) < min_notional:
            raise ValueError(f"quote amount {quote_amount} below minNotional {min_notional}")

    @staticmethod
    def _client_order_id(side: str) -> str:
        # Binance allows a user-supplied client order id; keep it short and unique.
        return f"qat{side[0]}{int(time.time()*1000):x}{uuid.uuid4().hex[:10]}"[:36]

    def query_order(self, symbol: str, *, client_order_id: str | None = None, order_id: str | None = None) -> dict:
        params = {"symbol": symbol.upper()}
        if order_id:
            params["orderId"] = order_id
        elif client_order_id:
            params["origClientOrderId"] = client_order_id
        else:
            raise ValueError("client_order_id or order_id required")
        return self._signed("GET", "/api/v3/order", params)

    def _resolve_unknown_order(self, symbol: str, client_order_id: str) -> dict:
        last = None
        for delay in (0.0, 0.2, 0.5):
            if delay:
                time.sleep(delay)
            try:
                return self.query_order(symbol, client_order_id=client_order_id)
            except BinanceAPIError as exc:
                last = exc
                # -2013 = order does not exist yet; do NOT submit another order.
                if exc.code != -2013:
                    raise
            except requests.RequestException as exc:
                last = exc
        raise OrderStatusUnknown(
            f"order status remains unknown for clientOrderId={client_order_id}; refusing automatic resubmission: {last}"
        )

    def _place_market(self, symbol: str, params: dict) -> dict:
        client_id = self._client_order_id(params["side"])
        body = {**params, "symbol": symbol.upper(), "type": "MARKET", "newOrderRespType": "FULL", "newClientOrderId": client_id}
        try:
            return self._signed("POST", "/api/v3/order", body)
        except requests.Timeout:
            return self._resolve_unknown_order(symbol, client_id)
        except BinanceAPIError as exc:
            if exc.code == -1007:
                return self._resolve_unknown_order(symbol, client_id)
            raise

    def _normalize_fill(self, symbol: str, side: str, raw: dict, market_price: float | None) -> Fill:
        info = self._symbol_info(symbol)
        base_asset, quote_asset = info["baseAsset"], info["quoteAsset"]
        executed = float(raw.get("executedQty", 0) or 0)
        quote = float(raw.get("cummulativeQuoteQty", 0) or 0)
        fee_quote = 0.0
        fee_base = 0.0
        unconverted = []
        for f in raw.get("fills", []) or []:
            commission = float(f.get("commission", 0) or 0)
            asset = str(f.get("commissionAsset", ""))
            if asset == quote_asset:
                fee_quote += commission
            elif asset == base_asset:
                fee_base += commission
            elif commission:
                unconverted.append({"asset": asset, "commission": commission})
        execution_px = quote / executed if executed else float(market_price or 0)
        if side == "BUY":
            normalized_base = max(0.0, executed - fee_base)
            normalized_quote = quote
        else:
            # If commission is charged in base, actual base debit exceeds executedQty.
            normalized_base = executed + fee_base
            normalized_quote = max(0.0, quote - fee_quote)
        enriched = dict(raw)
        enriched.update({
            "base_asset": base_asset,
            "quote_asset": quote_asset,
            "base_fee_qty": fee_base,
            "unconverted_commissions": unconverted,
            "commission_unconverted": bool(unconverted),
            "fee_in_quote_qty": side == "SELL",  # SELL quote_qty is normalized net proceeds.
        })
        return Fill(side, execution_px, normalized_base, normalized_quote, fee_quote, str(raw.get("orderId", "")), enriched)

    def market_buy(self, symbol: str, quote_amount: float, market_price: float | None = None) -> Fill:
        self._validate_market_notional(symbol, quote_amount)
        raw = self._place_market(symbol, {
            "side": "BUY",
            "quoteOrderQty": f"{quote_amount:.8f}",
        })
        return self._normalize_fill(symbol, "BUY", raw, market_price)

    def market_sell(self, symbol: str, base_qty: float, market_price: float | None = None) -> Fill:
        qty_str = self._round_qty(symbol, base_qty)
        raw = self._place_market(symbol, {
            "side": "SELL",
            "quantity": qty_str,
        })
        return self._normalize_fill(symbol, "SELL", raw, market_price)

    def account(self) -> dict:
        return self._signed("GET", "/api/v3/account", {"omitZeroBalances": "true"})

    def account_balances(self, symbol: str) -> dict:
        info = self._symbol_info(symbol)
        wanted = {info["baseAsset"], info["quoteAsset"]}
        acct = self.account()
        found = {}
        for row in acct.get("balances", []):
            asset = row.get("asset")
            if asset in wanted:
                found[asset] = float(row.get("free", 0) or 0) + float(row.get("locked", 0) or 0)
        return {
            "base_asset": info["baseAsset"],
            "quote_asset": info["quoteAsset"],
            "base_balance": found.get(info["baseAsset"], 0.0),
            "quote_balance": found.get(info["quoteAsset"], 0.0),
            "account_update_time": acct.get("updateTime"),
        }
