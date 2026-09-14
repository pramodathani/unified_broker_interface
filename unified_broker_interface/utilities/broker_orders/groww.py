"""
Groww orders and trades, from `GET https://api.groww.in/v1/order/list` and
`GET https://api.groww.in/v1/order/trades/{groww_order_id}?segment=`.

The API client unwraps Groww's `payload`. Following Groww's published schema, `order_list` holds rows carrying
`groww_order_id`, `order_status` and `remark`, `trading_symbol` - Groww sends no token, so a cash order is
resolved by its symbol - on `exchange` in Groww's `segment` (`CASH`, `FNO`, `COMMODITY`), `transaction_type`,
`product`, `order_type`, `validity`, `quantity`, `filled_quantity`, `remaining_quantity`, `price`,
`trigger_price`, `average_fill_price`, `created_at`, `exchange_time` and `order_reference_id`. An empty book is
`{"order_list": []}`, measured on 2026-09-13.

Groww has no single trade book: an order's fills are asked for by its id and segment. So the trade book is
built from today's order list, asking only for the orders that have filled anything, all of them at once.
A fill row carries `groww_trade_id`, `groww_order_id`, `exchange_trade_id`, `exchange_order_id`,
`trading_symbol`, `exchange`, `segment`, `product`, `transaction_type`, `quantity`, `price`,
`trade_date_time` and `created_at`.

**Writing.** An order is placed with `POST /v1/order/create` and a JSON body of `trading_symbol`, `quantity`,
`price`, `trigger_price`, `validity`, `exchange`, `segment`, `product`, `order_type` (`MARKET`, `LIMIT`, `SL`,
`SL_M`), `transaction_type` and `order_reference_id` - 8 to 20 letters, digits and hyphens, unique per order - made
from the tag and a random suffix, and answered as the placement's `tag` so the order can be found in the order
book. Groww answers with `groww_order_id`. It takes no after-market orders. A modification is
`POST /v1/order/modify` restating `order_type`, `quantity`, `price` and `trigger_price` with the order's segment -
Groww does not modify validity or disclosed quantity - and a cancellation `POST /v1/order/cancel` with the id and
segment.

Groww refuses with an error code: `GA001` bad request, `GA004` not found, `GA005` forbidden, `GA006` rate limited
and `GA007` a duplicate reference settle a write; `GA000` and `GA003`, its internal and unavailable errors, leave
the outcome unknown.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor

from unified_broker_interface.utilities.broker_holdings.base import canonical_exchange
from unified_broker_interface.utilities.broker_holdings.groww import GrowwHoldingsSource
from unified_broker_interface.utilities.broker_orders.base import (ORDER_TYPES, PRODUCTS, STATUSES, TRANSACTION_TYPES,
                                                                   VALIDITIES, BrokerOrdersSource, OrdersUnavailable,
                                                                   UnsupportedOrder, normalize, number, order,
                                                                   order_venue, text, trade)
from unified_broker_interface.utilities.broker_positions.groww import SEGMENT_KINDS

ORDERS_URL = "https://api.groww.in/v1/order/list"
TRADES_URL = "https://api.groww.in/v1/order/trades/{order_id}"

PLACE_URL = "https://api.groww.in/v1/order/create"
MODIFY_URL = "https://api.groww.in/v1/order/modify"
CANCEL_URL = "https://api.groww.in/v1/order/cancel"

SEGMENT_CODES = {("nse", "cash"): "CASH", ("bse", "cash"): "CASH", ("nse", "derivative"): "FNO",
                 ("bse", "derivative"): "FNO"}
ORDER_TYPE_CODES = {"MARKET": "MARKET", "LIMIT": "LIMIT", "SL": "SL", "SL-M": "SL_M"}

# Groww's error codes that settle a write as not done.
REJECTION_CODES = ("GA001", "GA004", "GA005", "GA006", "GA007")

# The most per-order trade calls sent to Groww at once.
TRADE_CALLS_AT_ONCE = 8

def _venue(row):
    """
    A Groww row's canonical exchange and kind, from its exchange and Groww segment.
    """
    exchange = row.get("exchange")
    return (canonical_exchange(exchange) or str(exchange or "").lower() or None,
            SEGMENT_KINDS.get(str(row.get("segment") or "").upper()))

class GrowwOrdersSource(BrokerOrdersSource):
    """
    Reads Groww orders and trades.
    """

    BROKER_NAME = "groww"
    WRITES_ENABLED = True
    SUPPORTS_AFTER_MARKET = False
    MODIFIABLE_FIELDS = ("quantity", "price", "trigger_price", "order_type")

    def _get(self, client, url, key, name, parameters=None):
        data = (client.get(url=url, params=parameters, timeout=self.TIMEOUT_SECONDS) or {}).get("data")
        if data is None:
            return []
        if not isinstance(data, dict) or not isinstance(data.get(key, []), list):
            raise OrdersUnavailable(f"Groww answered the {name} request without a {name}: {str(data)[:200]}")
        return data.get(key) or []

    def fetch_orders(self, client):
        return self._get(client, ORDERS_URL, "order_list", "order list")

    def fetch_trades(self, client):
        filled = [row for row in self.fetch_orders(client)
                  if isinstance(row, dict) and row.get("groww_order_id") and number(row.get("filled_quantity"))]
        if not filled:
            return []
        with ThreadPoolExecutor(max_workers=min(len(filled), TRADE_CALLS_AT_ONCE),
                                thread_name_prefix="groww-trades") as pool:
            futures = [pool.submit(self._get, client, TRADES_URL.format(order_id=row["groww_order_id"]), "trade_list",
                                   "trade list", {"segment": row.get("segment")}) for row in filled]
        return [fill for future in futures for fill in future.result()]

    def normalize_order(self, row):
        exchange, symbol = row.get("exchange"), row.get("trading_symbol")
        return order(
            self.BROKER_NAME, exchange, _venue(row),
            order_id=text(row.get("groww_order_id")),
            status=normalize(row.get("order_status"), STATUSES),
            status_message=row.get("remark") or None,
            id=f"{exchange}:{symbol}" if exchange and symbol else symbol,
            tradingsymbol=symbol,
            transaction_type=normalize(row.get("transaction_type"), TRANSACTION_TYPES),
            product=normalize(row.get("product"), PRODUCTS),
            order_type=normalize(row.get("order_type"), ORDER_TYPES),
            validity=normalize(row.get("validity"), VALIDITIES),
            quantity=number(row.get("quantity"), int),
            filled_quantity=number(row.get("filled_quantity"), int),
            pending_quantity=number(row.get("remaining_quantity"), int),
            price=number(row.get("price")),
            trigger_price=number(row.get("trigger_price")),
            average_price=number(row.get("average_fill_price")),
            order_timestamp=row.get("created_at"),
            exchange_timestamp=row.get("exchange_time"),
            tag=row.get("order_reference_id"),
        )

    def normalize_trade(self, row):
        return trade(
            self.BROKER_NAME, row.get("exchange"), _venue(row),
            trade_id=text(row.get("groww_trade_id")),
            order_id=text(row.get("groww_order_id")),
            exchange_order_id=text(row.get("exchange_order_id")),
            exchange_trade_id=text(row.get("exchange_trade_id")),
            tradingsymbol=row.get("trading_symbol"),
            transaction_type=normalize(row.get("transaction_type"), TRANSACTION_TYPES),
            product=normalize(row.get("product"), PRODUCTS),
            quantity=number(row.get("quantity"), int),
            price=number(row.get("price")),
            trade_timestamp=row.get("trade_date_time") or row.get("created_at"),
        )

    is_authentication_error = GrowwHoldingsSource.is_authentication_error

    def build_place(self, order_request, identity, handle):
        if order_request["after_market"]:
            raise UnsupportedOrder("groww takes no after-market orders")
        if not handle.get("order_symbol"):
            raise UnsupportedOrder(f"the groww mapping carries no trading symbol for {identity['instrument_id']}")
        reference = f"{(order_request['tag'] or 'ubi')[:7]}-{uuid.uuid4().hex[:12]}"
        return {"method": "POST", "url": PLACE_URL, "tag": reference, "json": {
            "trading_symbol": handle["order_symbol"],
            "quantity": order_request["quantity"],
            "price": float(order_request["price"] or 0),
            "trigger_price": float(order_request["trigger_price"] or 0),
            "validity": order_request["validity"],
            "exchange": identity["exchange"].upper(),
            "segment": order_venue(self.BROKER_NAME, identity, SEGMENT_CODES),
            "product": order_request["product"],
            "order_type": ORDER_TYPE_CODES[order_request["order_type"]],
            "transaction_type": order_request["transaction_type"],
            "order_reference_id": reference,
        }}

    def build_modify(self, row, changes):
        values = self.modified_values(row, changes)
        return {"method": "POST", "url": MODIFY_URL, "json": {
            "groww_order_id": str(row["groww_order_id"]),
            "segment": row.get("segment"),
            "order_type": ORDER_TYPE_CODES.get(values["order_type"], values["order_type"]),
            "quantity": values["quantity"],
            "price": float(values["price"] or 0),
            "trigger_price": float(values["trigger_price"] or 0),
        }}

    def build_cancel(self, row):
        return {"method": "POST", "url": CANCEL_URL,
                "json": {"groww_order_id": str(row["groww_order_id"]), "segment": row.get("segment")}}

    def written_order_id(self, response):
        data = (response or {}).get("data")
        return text(data.get("groww_order_id")) if isinstance(data, dict) else None

    def write_error(self, response):
        data = (response or {}).get("data")
        if isinstance(data, dict) and data.get("status") not in (None, "SUCCESS"):
            error = data.get("error")
            return str((error.get("message") if isinstance(error, dict) else error) or data.get("message")
                       or f"status {data.get('status')}")
        return None

    def is_rejection(self, exception):
        return str(getattr(exception, "code", "")).upper() in REJECTION_CODES
