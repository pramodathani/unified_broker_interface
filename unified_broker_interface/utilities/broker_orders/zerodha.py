"""
Zerodha (Kite) orders and trades, from `GET https://api.kite.trade/orders` and `GET https://api.kite.trade/trades`.

The API client unwraps Kite's `data`, a list in both cases. An order-book row is the same object Kite posts
on its order websocket: `order_id`, `exchange_order_id`, `parent_order_id`, `status` and `status_message`,
`tradingsymbol` and `instrument_token` on `exchange` (`NSE`, `NFO`, `MCX`...), `transaction_type`,
`product`, `order_type`, `validity`, the quantities, `price`, `trigger_price`, `average_price`,
`order_timestamp`, `exchange_timestamp` and `tag`.

A trade-book row carries `trade_id`, `order_id`, `exchange_order_id`, `tradingsymbol`, `instrument_token`,
`exchange`, `transaction_type`, `product`, `quantity`, `average_price` - the fill price - and
`fill_timestamp` and `exchange_timestamp`.

A dead session is refused with HTTP 403 and `error_type` `TokenException`.

**Writing.** An order is placed with `POST /orders/{variety}` - `regular`, or `amo` after the market - and a
form body of `tradingsymbol`, `exchange`, `transaction_type`, `order_type`, `quantity`, `product`,
`validity`, `price`, `trigger_price`, `disclosed_quantity` and an optional `tag` of up to twenty letters and
digits. Kite takes a market rather than a listing exchange: a cash instrument is `NSE` or `BSE`, an equity
derivative `NFO` or `BFO`. The price and trigger price are sent as zero when the order type does not use
them, which is what Kite expects. Kite answers with the new `order_id`.

A modification is `PUT /orders/{variety}/{order_id}` carrying only the fields that change - Kite leaves the
rest as they are - and a cancellation `DELETE /orders/{variety}/{order_id}`. The variety comes from the
order's row in the order book.

Kite refuses a bad order with an error status and an `error_type` - `InputException`, `OrderException`,
`MarginException`, `HoldingException`, `PermissionException` - which is a settled rejection. A
`NetworkException`, `GeneralException` or `DataException`, or no answer, leaves the outcome unknown.

**Not yet sent.** Commodity and currency derivatives are refused: Kite counts their order quantity in lots
where every other order is in units, and that has not been confirmed. Nothing has been placed live.
"""

from unified_broker_interface.utilities.broker_holdings.zerodha import ZerodhaHoldingsSource
from unified_broker_interface.utilities.broker_orders.base import (ORDER_TYPES, PRODUCTS, STATUSES, TRANSACTION_TYPES,
                                                                   VALIDITIES, BrokerOrdersSource, OrdersUnavailable,
                                                                   UnsupportedOrder, normalize, number, order,
                                                                   order_venue, text, trade)

ORDERS_URL = "https://api.kite.trade/orders"
TRADES_URL = "https://api.kite.trade/trades"

# Kite's market for an order, by exchange and kind of instrument.
EXCHANGE_CODES = {("nse", "cash"): "NSE", ("bse", "cash"): "BSE", ("nse", "derivative"): "NFO", ("bse", "derivative"): "BFO"}

# Kite's refusals that settle an order as not placed, modified or cancelled.
REJECTIONS = ("InputException", "OrderException", "MarginException", "HoldingException", "PermissionException")

class ZerodhaOrdersSource(BrokerOrdersSource):
    """
    Reads Zerodha orders and trades.
    """

    BROKER_NAME = "zerodha"
    WRITES_ENABLED = True

    def _book(self, client, url, name):
        data = (client.get(url=url, timeout=self.TIMEOUT_SECONDS) or {}).get("data")
        if data is None:
            return []
        if not isinstance(data, list):
            raise OrdersUnavailable(f"Kite answered the {name} request without a {name}: {str(data)[:200]}")
        return data

    def fetch_orders(self, client):
        return self._book(client, ORDERS_URL, "order book")

    def fetch_trades(self, client):
        return self._book(client, TRADES_URL, "trade book")

    def normalize_order(self, row):
        exchange, symbol = row.get("exchange"), row.get("tradingsymbol")
        return order(
            self.BROKER_NAME, exchange,
            order_id=text(row.get("order_id")),
            exchange_order_id=text(row.get("exchange_order_id")),
            parent_order_id=text(row.get("parent_order_id")),
            status=normalize(row.get("status"), STATUSES),
            status_message=row.get("status_message") or row.get("status_message_raw"),
            id=f"{exchange}:{symbol}" if exchange and symbol else symbol,
            instrument_token=text(row.get("instrument_token")),
            tradingsymbol=symbol,
            transaction_type=normalize(row.get("transaction_type"), TRANSACTION_TYPES),
            product=normalize(row.get("product"), PRODUCTS),
            order_type=normalize(row.get("order_type"), ORDER_TYPES),
            validity=normalize(row.get("validity"), VALIDITIES),
            quantity=number(row.get("quantity"), int),
            filled_quantity=number(row.get("filled_quantity"), int),
            pending_quantity=number(row.get("pending_quantity"), int),
            cancelled_quantity=number(row.get("cancelled_quantity"), int),
            disclosed_quantity=number(row.get("disclosed_quantity"), int),
            price=number(row.get("price")),
            trigger_price=number(row.get("trigger_price")),
            average_price=number(row.get("average_price")),
            order_timestamp=row.get("order_timestamp"),
            exchange_timestamp=row.get("exchange_timestamp") or row.get("exchange_update_timestamp"),
            tag=row.get("tag"),
        )

    def normalize_trade(self, row):
        return trade(
            self.BROKER_NAME, row.get("exchange"),
            trade_id=text(row.get("trade_id")),
            order_id=text(row.get("order_id")),
            exchange_order_id=text(row.get("exchange_order_id")),
            instrument_token=text(row.get("instrument_token")),
            tradingsymbol=row.get("tradingsymbol"),
            transaction_type=normalize(row.get("transaction_type"), TRANSACTION_TYPES),
            product=normalize(row.get("product"), PRODUCTS),
            quantity=number(row.get("quantity"), int),
            price=number(row.get("average_price")),
            trade_timestamp=row.get("fill_timestamp"),
            exchange_timestamp=row.get("exchange_timestamp"),
        )

    is_authentication_error = ZerodhaHoldingsSource.is_authentication_error

    def build_place(self, order_request, identity, handle):
        if not handle.get("order_symbol"):
            raise UnsupportedOrder(f"the zerodha mapping carries no trading symbol for {identity['instrument_id']}")
        form = {
            "tradingsymbol": handle["order_symbol"],
            "exchange": order_venue(self.BROKER_NAME, identity, EXCHANGE_CODES),
            "transaction_type": order_request["transaction_type"],
            "order_type": order_request["order_type"],
            "quantity": order_request["quantity"],
            "product": order_request["product"],
            "validity": order_request["validity"],
            "price": str(order_request["price"] or 0),
            "trigger_price": str(order_request["trigger_price"] or 0),
            "disclosed_quantity": order_request["disclosed_quantity"] or 0,
        }
        if order_request["tag"]:
            form["tag"] = order_request["tag"]
        variety = "amo" if order_request["after_market"] else "regular"
        return {"method": "POST", "url": f"{ORDERS_URL}/{variety}", "form": form}

    def build_modify(self, row, changes):
        form = {}
        for field in ("quantity", "order_type", "validity", "disclosed_quantity"):
            if changes.get(field) is not None:
                form[field] = changes[field]
        for field in ("price", "trigger_price"):
            if changes.get(field) is not None:
                form[field] = str(changes[field])
        return {"method": "PUT", "url": f"{ORDERS_URL}/{row.get('variety') or 'regular'}/{row['order_id']}", "form": form}

    def build_cancel(self, row):
        return {"method": "DELETE", "url": f"{ORDERS_URL}/{row.get('variety') or 'regular'}/{row['order_id']}"}

    def written_order_id(self, response):
        data = (response or {}).get("data")
        return text(data.get("order_id")) if isinstance(data, dict) else None

    def is_rejection(self, exception):
        return getattr(exception, "code", None) in REJECTIONS
