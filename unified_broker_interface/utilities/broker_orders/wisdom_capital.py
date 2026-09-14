"""
Wisdom Capital orders and trades, from Symphony XTS's `GET https://trade.wisdomcapital.in/interactive/orders` and
`GET https://trade.wisdomcapital.in/interactive/orders/trades`.

Both name the account as `clientID` on the interactive session, and the API client unwraps XTS's `result`, a
list; an empty book is `[]`, measured on 2026-09-13 for both. An order-book row is the same object XTS pushes as
an order event: `AppOrderID`, `ExchangeOrderID`, `OrderReferenceID`, `OrderStatus` and `CancelRejectReason`,
`TradingSymbol` and `ExchangeInstrumentID` in `ExchangeSegment` (`NSECM`, `NSEFO`...), `OrderSide`,
`ProductType`, `OrderType`, `TimeInForce`, `OrderQuantity`, `CumulativeQuantity`, `LeavesQuantity`,
`CancelledQuantity`, `OrderDisclosedQuantity`, `OrderPrice`, `OrderStopPrice`, `OrderAverageTradedPrice`,
`OrderGeneratedDateTime`, `ExchangeTransactTime` and `OrderUniqueIdentifier`. Following XTS's published schema,
a trade row carries `ExecutionID`, the same order and instrument fields, `LastTradedQuantity` and
`LastTradedPrice`, the quantity and price of that fill, and `LastExecutionTransactTime`.

**Writing.** An order is placed with `POST /interactive/orders` and a JSON body of `exchangeSegment` (`NSECM`,
`NSEFO`, `BSECM`, `BSEFO`), `exchangeInstrumentID`, `productType`, `orderType` in the XTS SDK's constants (`MARKET`,
`LIMIT`, `STOPLIMIT`, `STOPMARKET`), `orderSide`, `timeInForce`, `disclosedQuantity`, `orderQuantity`, `limitPrice`,
`stopPrice`, `orderUniqueIdentifier` for the tag and `clientID`; XTS answers with `AppOrderID` and takes no
after-market orders. A modification is `PUT /interactive/orders` restating the order's product, type, quantity,
disclosed quantity, prices and validity as `modified...` fields, with the changes laid over its current values; a
cancellation is `DELETE /interactive/orders` with `appOrderID` and `orderUniqueIdentifier` as parameters. The client
id comes from Wisdom Capital's settings.

XTS refuses an order with an `e-orders` or `e-rms` code, which settles it; any other failure leaves the outcome
unknown.
"""

from unified_broker_interface.utilities.broker_holdings.wisdom_capital import WisdomCapitalHoldingsSource
from unified_broker_interface.utilities.broker_orders.base import (ORDER_TYPES, PRODUCTS, STATUSES, TRANSACTION_TYPES,
                                                                   VALIDITIES, BrokerOrdersSource, OrdersUnavailable,
                                                                   UnsupportedOrder, normalize, number, order,
                                                                   order_venue, text, trade)

ORDERS_URL = "https://trade.wisdomcapital.in/interactive/orders"
TRADES_URL = "https://trade.wisdomcapital.in/interactive/orders/trades"

SEGMENT_CODES = {("nse", "cash"): "NSECM", ("bse", "cash"): "BSECM", ("nse", "derivative"): "NSEFO",
                 ("bse", "derivative"): "BSEFO"}
ORDER_TYPE_CODES = {"MARKET": "MARKET", "LIMIT": "LIMIT", "SL": "STOPLIMIT", "SL-M": "STOPMARKET"}

# The order reference sent when a placement carries no tag.
DEFAULT_REFERENCE = "ubi"

# The XTS error code prefixes that settle a write as refused.
REJECTION_PREFIXES = ("e-orders", "e-order", "e-rms")

class WisdomCapitalOrdersSource(BrokerOrdersSource):
    """
    Reads Wisdom Capital orders and trades.
    """

    BROKER_NAME = "wisdom_capital"
    WRITES_ENABLED = True
    SUPPORTS_AFTER_MARKET = False

    def _book(self, client, url, name):
        response = client.get(url=url, params={"clientID": client._settings.get("ucc_code", "")},
                              timeout=self.TIMEOUT_SECONDS)
        data = (response or {}).get("data")
        if data is None:
            return []
        if not isinstance(data, list):
            raise OrdersUnavailable(f"XTS answered the {name} request without a {name}: {str(data)[:200]}")
        return data

    def fetch_orders(self, client):
        return self._book(client, ORDERS_URL, "order book")

    def fetch_trades(self, client):
        return self._book(client, TRADES_URL, "trade book")

    def normalize_order(self, row):
        segment = row.get("ExchangeSegment")
        symbol = row.get("TradingSymbol") or row.get("TradingSymbolName")
        quantity = number(row.get("OrderQuantity"), int)
        filled = number(row.get("CumulativeQuantity"), int)
        pending = number(row.get("LeavesQuantity"), int)
        if pending is None and quantity is not None and filled is not None:
            pending = quantity - filled
        return order(
            self.BROKER_NAME, segment,
            order_id=text(row.get("AppOrderID")),
            exchange_order_id=text(row.get("ExchangeOrderID")),
            parent_order_id=text(row.get("OrderReferenceID")),
            status=normalize(row.get("OrderStatus"), STATUSES),
            status_message=row.get("CancelRejectReason") or None,
            id=f"{segment}:{symbol}" if segment and symbol else symbol,
            instrument_token=text(row.get("ExchangeInstrumentID")),
            tradingsymbol=symbol,
            transaction_type=normalize(row.get("OrderSide"), TRANSACTION_TYPES),
            product=normalize(row.get("ProductType"), PRODUCTS),
            order_type=normalize(row.get("OrderType"), ORDER_TYPES),
            validity=normalize(row.get("TimeInForce"), VALIDITIES),
            quantity=quantity,
            filled_quantity=filled,
            pending_quantity=pending,
            cancelled_quantity=number(row.get("CancelledQuantity"), int),
            disclosed_quantity=number(row.get("OrderDisclosedQuantity"), int),
            price=number(row.get("OrderPrice")),
            trigger_price=number(row.get("OrderStopPrice")),
            average_price=number(row.get("OrderAverageTradedPrice")),
            order_timestamp=row.get("OrderGeneratedDateTime") or row.get("LastUpdateDateTime"),
            exchange_timestamp=row.get("ExchangeTransactTime"),
            tag=row.get("OrderUniqueIdentifier"),
        )

    def normalize_trade(self, row):
        return trade(
            self.BROKER_NAME, row.get("ExchangeSegment"),
            trade_id=text(row.get("ExecutionID")),
            order_id=text(row.get("AppOrderID")),
            exchange_order_id=text(row.get("ExchangeOrderID")),
            exchange_trade_id=text(row.get("ExecutionID")),
            instrument_token=text(row.get("ExchangeInstrumentID")),
            tradingsymbol=row.get("TradingSymbol"),
            transaction_type=normalize(row.get("OrderSide"), TRANSACTION_TYPES),
            product=normalize(row.get("ProductType"), PRODUCTS),
            quantity=number(row.get("LastTradedQuantity"), int),
            price=number(row.get("LastTradedPrice")),
            trade_timestamp=row.get("LastExecutionTransactTime"),
            exchange_timestamp=row.get("ExchangeTransactTime"),
        )

    is_authentication_error = WisdomCapitalHoldingsSource.is_authentication_error

    def build_place(self, order_request, identity, handle):
        if order_request["after_market"]:
            raise UnsupportedOrder("wisdom_capital takes no after-market orders")
        token = str(handle["broker_token"])
        if not token.isdigit():
            raise UnsupportedOrder(f"the wisdom_capital mapping carries no numeric instrument id for {identity['instrument_id']}")
        return {"method": "POST", "url": ORDERS_URL, "json": {
            "exchangeSegment": order_venue(self.BROKER_NAME, identity, SEGMENT_CODES),
            "exchangeInstrumentID": int(token),
            "productType": order_request["product"],
            "orderType": ORDER_TYPE_CODES[order_request["order_type"]],
            "orderSide": order_request["transaction_type"],
            "timeInForce": order_request["validity"],
            "disclosedQuantity": order_request["disclosed_quantity"] or 0,
            "orderQuantity": order_request["quantity"],
            "limitPrice": float(order_request["price"] or 0),
            "stopPrice": float(order_request["trigger_price"] or 0),
            "orderUniqueIdentifier": order_request["tag"] or DEFAULT_REFERENCE,
        }}

    def build_modify(self, row, changes):
        values = self.modified_values(row, changes)
        return {"method": "PUT", "url": ORDERS_URL, "json": {
            "appOrderID": int(row["AppOrderID"]),
            "modifiedProductType": row.get("ProductType"),
            "modifiedOrderType": ORDER_TYPE_CODES.get(values["order_type"], values["order_type"]),
            "modifiedOrderQuantity": values["quantity"],
            "modifiedDisclosedQuantity": values["disclosed_quantity"] or 0,
            "modifiedLimitPrice": float(values["price"] or 0),
            "modifiedStopPrice": float(values["trigger_price"] or 0),
            "modifiedTimeInForce": values["validity"],
            "orderUniqueIdentifier": row.get("OrderUniqueIdentifier") or DEFAULT_REFERENCE,
        }}

    def build_cancel(self, row):
        return {"method": "DELETE", "url": ORDERS_URL, "params": {
            "appOrderID": int(row["AppOrderID"]),
            "orderUniqueIdentifier": row.get("OrderUniqueIdentifier") or DEFAULT_REFERENCE,
        }}

    def account_fields(self, client, request):
        client_id = client._settings.get("ucc_code", "")
        if request.get("json") is not None:
            return {**request, "json": {**request["json"], "clientID": client_id}}
        return {**request, "params": {**(request.get("params") or {}), "clientID": client_id}}

    def written_order_id(self, response):
        data = (response or {}).get("data")
        return text(data.get("AppOrderID")) if isinstance(data, dict) else None

    def write_error(self, response):
        data = (response or {}).get("data")
        if isinstance(data, dict) and data.get("type") not in (None, "success"):
            return str(data.get("description") or data.get("message") or data.get("code") or f"type {data.get('type')}")
        return None

    def is_rejection(self, exception):
        code = str(getattr(exception, "code", "") or "").lower()
        return code.startswith(REJECTION_PREFIXES)
