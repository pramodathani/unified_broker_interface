"""
Dhan orders and trades, from `GET https://api.dhan.co/v2/orders` and `GET https://api.dhan.co/v2/trades`.

The API client passes Dhan's lists through; an empty book is `[]`, measured on 2026-09-13. Following Dhan's
published v2 schema, an order row carries `orderId`, `exchangeOrderId`, `orderStatus` (`TRANSIT`, `PENDING`,
`PART_TRADED`, `TRADED`, `CANCELLED`, `REJECTED`, `EXPIRED`) with `omsErrorDescription`, `tradingSymbol` and
`securityId` in `exchangeSegment` (`NSE_EQ`, `NSE_FNO`, `MCX_COMM`...), `transactionType`, `productType`,
`orderType`, `validity`, `quantity`, `filledQty`, `remainingQuantity`, `disclosedQuantity`, `price`,
`triggerPrice`, `averageTradedPrice`, `createTime` and `exchangeTime`. A trade row carries `orderId`,
`exchangeOrderId`, `exchangeTradeId` - Dhan's only trade id - the same instrument fields, `tradedQuantity`,
`tradedPrice`, `createTime` and `exchangeTime`.

**Writing.** An order is placed with `POST /v2/orders` and a JSON body of `dhanClientId`, `transactionType`,
`exchangeSegment`, `productType` (`CNC`, `INTRADAY`, `MARGIN`), `orderType` (`MARKET`, `LIMIT`, `STOP_LOSS`,
`STOP_LOSS_MARKET`), `validity`, `securityId`, `quantity`, `disclosedQuantity`, `price`, `triggerPrice`,
`afterMarketOrder` - with `amoTime` `OPEN` for an after-market order - and `correlationId` for the tag. Dhan answers
with `orderId`. A modification is `PUT /v2/orders/{orderId}` and restates the whole order - type, validity,
quantity, price, trigger price and disclosed quantity - so it is built from the order's current values with the
changes laid over them. A cancellation is `DELETE /v2/orders/{orderId}`. The client id comes from Dhan's settings.

Dhan refuses a bad order with an error status and an `errorType`; an input, order or rate-limit error settles it,
and anything else - a server or network error - leaves the outcome unknown.
"""

from unified_broker_interface.utilities.broker_holdings.dhan import DhanHoldingsSource
from unified_broker_interface.utilities.broker_orders.base import (ORDER_TYPES, PRODUCTS, STATUSES, TRANSACTION_TYPES,
                                                                   VALIDITIES, BrokerOrdersSource, OrdersUnavailable,
                                                                   normalize, number, order, order_venue, text,
                                                                   trade)

ORDERS_URL = "https://api.dhan.co/v2/orders"
TRADES_URL = "https://api.dhan.co/v2/trades"

SEGMENT_CODES = {("nse", "cash"): "NSE_EQ", ("bse", "cash"): "BSE_EQ", ("nse", "derivative"): "NSE_FNO",
                 ("bse", "derivative"): "BSE_FNO"}
ORDER_TYPE_CODES = {"MARKET": "MARKET", "LIMIT": "LIMIT", "SL": "STOP_LOSS", "SL-M": "STOP_LOSS_MARKET"}
PRODUCT_CODES = {"CNC": "CNC", "MIS": "INTRADAY", "NRML": "MARGIN"}

# The words in Dhan's error types that mean an order was refused, lowercased.
REJECTION_MARKERS = ("input", "order", "rate_limit", "rate limit", "access")

class DhanOrdersSource(BrokerOrdersSource):
    """
    Reads Dhan orders and trades.
    """

    BROKER_NAME = "dhan"
    WRITES_ENABLED = True

    def _book(self, client, url, name):
        data = (client.get(url=url, timeout=self.TIMEOUT_SECONDS) or {}).get("data")
        if data is None:
            return []
        if not isinstance(data, list):
            raise OrdersUnavailable(f"Dhan answered the {name} request without a {name}: {str(data)[:200]}")
        return data

    def fetch_orders(self, client):
        return self._book(client, ORDERS_URL, "order book")

    def fetch_trades(self, client):
        return self._book(client, TRADES_URL, "trade book")

    def normalize_order(self, row):
        segment, symbol = row.get("exchangeSegment"), row.get("tradingSymbol")
        return order(
            self.BROKER_NAME, segment,
            order_id=text(row.get("orderId")),
            exchange_order_id=text(row.get("exchangeOrderId")),
            status=normalize(row.get("orderStatus"), STATUSES),
            status_message=row.get("omsErrorDescription") or None,
            id=f"{segment}:{symbol}" if segment and symbol else symbol,
            instrument_token=text(row.get("securityId")),
            tradingsymbol=symbol,
            transaction_type=normalize(row.get("transactionType"), TRANSACTION_TYPES),
            product=normalize(row.get("productType"), PRODUCTS),
            order_type=normalize(row.get("orderType"), ORDER_TYPES),
            validity=normalize(row.get("validity"), VALIDITIES),
            quantity=number(row.get("quantity"), int),
            filled_quantity=number(row.get("filledQty"), int),
            pending_quantity=number(row.get("remainingQuantity"), int),
            disclosed_quantity=number(row.get("disclosedQuantity"), int),
            price=number(row.get("price")),
            trigger_price=number(row.get("triggerPrice")),
            average_price=number(row.get("averageTradedPrice")),
            order_timestamp=row.get("createTime"),
            exchange_timestamp=row.get("exchangeTime"),
            tag=row.get("correlationId"),
        )

    def normalize_trade(self, row):
        return trade(
            self.BROKER_NAME, row.get("exchangeSegment"),
            trade_id=text(row.get("exchangeTradeId")),
            order_id=text(row.get("orderId")),
            exchange_order_id=text(row.get("exchangeOrderId")),
            exchange_trade_id=text(row.get("exchangeTradeId")),
            instrument_token=text(row.get("securityId")),
            tradingsymbol=row.get("tradingSymbol"),
            transaction_type=normalize(row.get("transactionType"), TRANSACTION_TYPES),
            product=normalize(row.get("productType"), PRODUCTS),
            quantity=number(row.get("tradedQuantity"), int),
            price=number(row.get("tradedPrice")),
            trade_timestamp=row.get("createTime"),
            exchange_timestamp=row.get("exchangeTime"),
        )

    is_authentication_error = DhanHoldingsSource.is_authentication_error

    def build_place(self, order_request, identity, handle):
        body = {
            "transactionType": order_request["transaction_type"],
            "exchangeSegment": order_venue(self.BROKER_NAME, identity, SEGMENT_CODES),
            "productType": PRODUCT_CODES[order_request["product"]],
            "orderType": ORDER_TYPE_CODES[order_request["order_type"]],
            "validity": order_request["validity"],
            "securityId": str(handle["broker_token"]),
            "quantity": order_request["quantity"],
            "disclosedQuantity": order_request["disclosed_quantity"] or 0,
            "price": float(order_request["price"] or 0),
            "triggerPrice": float(order_request["trigger_price"] or 0),
            "afterMarketOrder": order_request["after_market"],
        }
        if order_request["after_market"]:
            body["amoTime"] = "OPEN"
        if order_request["tag"]:
            body["correlationId"] = order_request["tag"]
        return {"method": "POST", "url": ORDERS_URL, "json": body}

    def build_modify(self, row, changes):
        values = self.modified_values(row, changes)
        return {"method": "PUT", "url": f"{ORDERS_URL}/{row['orderId']}", "json": {
            "orderId": str(row["orderId"]),
            "orderType": ORDER_TYPE_CODES.get(values["order_type"], values["order_type"]),
            "validity": values["validity"],
            "quantity": values["quantity"],
            "price": float(values["price"] or 0),
            "triggerPrice": float(values["trigger_price"] or 0),
            "disclosedQuantity": values["disclosed_quantity"] or 0,
        }}

    def build_cancel(self, row):
        return {"method": "DELETE", "url": f"{ORDERS_URL}/{row['orderId']}"}

    def account_fields(self, client, request):
        if request.get("json") is not None:
            request = {**request, "json": {"dhanClientId": str(client._settings["client_id"]), **request["json"]}}
        return request

    def written_order_id(self, response):
        data = (response or {}).get("data")
        return text(data.get("orderId")) if isinstance(data, dict) else None

    def is_rejection(self, exception):
        code = str(getattr(exception, "code", "") or "").lower()
        return any(marker in code for marker in REJECTION_MARKERS)
