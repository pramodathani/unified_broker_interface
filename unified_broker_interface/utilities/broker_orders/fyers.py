"""
Fyers orders and trades, from `GET https://api-t1.fyers.in/api/v3/orders` and `GET https://api-t1.fyers.in/api/v3/tradebook`.

The bodies have no `data` envelope, so the API client passes them through whole: the orders are `orderBook`
and the trades `tradeBook`. Following Fyers' published v3 schema, an order row carries `id`, `exchOrdId`,
`parentId`, `status` - a number, read with `STATUS_CODES` - and `message`, `symbol` (`NSE:KWIL-EQ`, whose
prefix is the exchange) and `fyToken`, `segment` (10 cash, 11 derivatives, 12 currency, 20 commodities),
`side` (1 buy, -1 sell), `type` (1 limit, 2 market, 3 stop market, 4 stop limit), `productType`,
`orderValidity`, `qty`, `filledQty`, `remainingQuantity`, `disclosedQty`, `limitPrice`, `stopPrice`,
`tradedPrice`, `orderDateTime` and `orderTag`. A trade row carries `tradeNumber`, `orderNumber`,
`exchangeOrderNo`, `symbol`, `fyToken`, `segment`, `side`, `productType`, `tradedQty`, `tradePrice` and
`orderDateTime`.

**Not read back live.** Every request on 2026-09-13 met Fyers' request limit. Refusals are read as for funds
and share its pause; see `broker_funds/fyers.py`.

**Writing - built, not enabled.** The Fyers app is not approved for placing orders. So the builds exist and are
checked offline, but Fyers is not offered to the router and a modify or cancel answers `501`, until a sign-off test
shows writes are allowed. An order would be placed with `POST /api/v3/orders/sync` and a JSON body of `symbol`, `qty`,
`type` (1 limit, 2 market, 3 stop market, 4 stop limit), `side` (1, -1), `productType` (`CNC`, `INTRADAY`, `MARGIN`),
`limitPrice`, `stopPrice`, `validity`, `disclosedQty`, `offlineOrder` for after-market and `orderTag`, answered with
`id`; modified with `PATCH` carrying the id and the changed fields, and cancelled with `DELETE` and the id.
"""

from stock_brokers.api.fyers import FyersAPIException
from unified_broker_interface.utilities.broker_funds import fyers as fyers_refusals
from unified_broker_interface.utilities.broker_orders.base import (ORDER_TYPES, PRODUCTS, STATUSES, TRANSACTION_TYPES,
                                                                   VALIDITIES, BrokerOrdersSource, OrdersUnavailable,
                                                                   UnsupportedOrder, normalize, number, order,
                                                                   order_venue, text, trade)
from unified_broker_interface.utilities.broker_positions.fyers import SEGMENT_KINDS

ORDERS_URL = "https://api-t1.fyers.in/api/v3/orders"
TRADES_URL = "https://api-t1.fyers.in/api/v3/tradebook"

SYNC_URL = "https://api-t1.fyers.in/api/v3/orders/sync"

VENUES = {("nse", "cash"): "cash", ("bse", "cash"): "cash", ("nse", "derivative"): "derivative",
          ("bse", "derivative"): "derivative"}
ORDER_TYPE_CODES = {"LIMIT": 1, "MARKET": 2, "SL-M": 3, "SL": 4}
SIDE_CODES = {"BUY": 1, "SELL": -1}
PRODUCT_CODES = {"CNC": "CNC", "MIS": "INTRADAY", "NRML": "MARGIN"}

# Fyers' own numeric order states. Kept here rather than in the shared status table, because a bare integer means
# different things to different brokers.
STATUS_CODES = {
    1: "CANCELLED",
    2: "COMPLETE",
    3: "COMPLETE",        # documented as reserved; treated as filled if it ever appears
    4: "OPEN",            # transit
    5: "REJECTED",
    6: "PENDING",
}

def _status(value):
    """
    Fyers' numeric order status, read with `STATUS_CODES`, or a word through the shared vocabulary.
    """
    code = number(value, int)
    if code is not None and code in STATUS_CODES:
        return STATUS_CODES[code]
    return normalize(value, STATUSES)

def _venue(row):
    """
    A Fyers row's canonical exchange, from its symbol's prefix, and kind, from its segment code.
    """
    prefix = str(row.get("symbol") or "").partition(":")[0]
    return (prefix.lower() or None, SEGMENT_KINDS.get(str(row.get("segment"))))

class FyersOrdersSource(BrokerOrdersSource):
    """
    Reads Fyers orders and trades.
    """

    BROKER_NAME = "fyers"
    WRITES_BLOCKED_REASON = "has an API app not approved for placing orders"

    def _book(self, client, url, key, name):
        fyers_refusals.paused(f"{name}s")
        try:
            data = (client.get(url=url, timeout=self.TIMEOUT_SECONDS) or {}).get("data")
        except FyersAPIException as exception:
            fyers_refusals.note_refusal(exception, name)
            raise
        if not isinstance(data, dict):
            raise OrdersUnavailable(f"Fyers answered the {name} request without a {name}: {str(data)[:200]}")
        if data.get("s") not in (None, "ok"):
            # Fyers can refuse inside a 200; raised as the API client would, so the session codes are seen.
            exception = FyersAPIException(code=data.get("code"), message=data.get("message"))
            fyers_refusals.note_refusal(exception, name)
            raise exception
        return data.get(key) or []

    def fetch_orders(self, client):
        return self._book(client, ORDERS_URL, "orderBook", "order book")

    def fetch_trades(self, client):
        return self._book(client, TRADES_URL, "tradeBook", "trade book")

    def normalize_order(self, row):
        symbol = row.get("symbol")
        return order(
            self.BROKER_NAME, symbol.partition(":")[0] if symbol else None, _venue(row),
            order_id=text(row.get("id")),
            exchange_order_id=text(row.get("exchOrdId")),
            parent_order_id=text(row.get("parentId")),
            status=_status(row.get("status")),
            status_message=row.get("message") or None,
            id=symbol,
            instrument_token=text(row.get("fyToken")),
            tradingsymbol=symbol,
            transaction_type=normalize(row.get("side"), TRANSACTION_TYPES),
            product=normalize(row.get("productType"), PRODUCTS),
            order_type=normalize(row.get("type"), ORDER_TYPES),
            validity=normalize(row.get("orderValidity"), VALIDITIES),
            quantity=number(row.get("qty"), int),
            filled_quantity=number(row.get("filledQty"), int),
            pending_quantity=number(row.get("remainingQuantity"), int),
            disclosed_quantity=number(row.get("disclosedQty"), int),
            price=number(row.get("limitPrice")),
            trigger_price=number(row.get("stopPrice")),
            average_price=number(row.get("tradedPrice")),
            order_timestamp=row.get("orderDateTime"),
            tag=row.get("orderTag"),
        )

    def normalize_trade(self, row):
        symbol = row.get("symbol")
        return trade(
            self.BROKER_NAME, symbol.partition(":")[0] if symbol else None, _venue(row),
            trade_id=text(row.get("tradeNumber")),
            order_id=text(row.get("orderNumber")),
            exchange_order_id=text(row.get("exchangeOrderNo")),
            instrument_token=text(row.get("fyToken")),
            tradingsymbol=symbol,
            transaction_type=normalize(row.get("side"), TRANSACTION_TYPES),
            product=normalize(row.get("productType"), PRODUCTS),
            quantity=number(row.get("tradedQty"), int),
            price=number(row.get("tradePrice")),
            trade_timestamp=row.get("orderDateTime"),
        )

    def is_authentication_error(self, exception):
        return fyers_refusals.is_authentication_error(exception)

    def build_place(self, order_request, identity, handle):
        order_venue(self.BROKER_NAME, identity, VENUES)
        if not handle.get("order_symbol"):
            raise UnsupportedOrder(f"the fyers mapping carries no symbol for {identity['instrument_id']}")
        body = {
            "symbol": handle["order_symbol"],
            "qty": order_request["quantity"],
            "type": ORDER_TYPE_CODES[order_request["order_type"]],
            "side": SIDE_CODES[order_request["transaction_type"]],
            "productType": PRODUCT_CODES[order_request["product"]],
            "limitPrice": float(order_request["price"] or 0),
            "stopPrice": float(order_request["trigger_price"] or 0),
            "validity": order_request["validity"],
            "disclosedQty": order_request["disclosed_quantity"] or 0,
            "offlineOrder": order_request["after_market"],
        }
        if order_request["tag"]:
            body["orderTag"] = order_request["tag"]
        return {"method": "POST", "url": SYNC_URL, "json": body}

    def build_modify(self, row, changes):
        body = {"id": str(row["id"])}
        for field, name in (("quantity", "qty"), ("disclosed_quantity", "disclosedQty")):
            if changes.get(field) is not None:
                body[name] = changes[field]
        for field, name in (("price", "limitPrice"), ("trigger_price", "stopPrice")):
            if changes.get(field) is not None:
                body[name] = float(changes[field])
        if changes.get("order_type"):
            body["type"] = ORDER_TYPE_CODES[changes["order_type"]]
        return {"method": "PATCH", "url": SYNC_URL, "json": body}

    def build_cancel(self, row):
        return {"method": "DELETE", "url": SYNC_URL, "json": {"id": str(row["id"])}}

    def send(self, client, request):
        fyers_refusals.paused("orders")
        try:
            response = super().send(client, request)
        except FyersAPIException as exception:
            fyers_refusals.note_refusal(exception, "order")
            raise
        return response

    def written_order_id(self, response):
        data = (response or {}).get("data")
        return text(data.get("id")) if isinstance(data, dict) else None

    def write_error(self, response):
        data = (response or {}).get("data")
        if isinstance(data, dict) and data.get("s") not in (None, "ok"):
            return str(data.get("message") or f"s {data.get('s')}")
        return None
