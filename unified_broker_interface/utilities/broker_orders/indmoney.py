"""
INDmoney (INDstocks) orders and trades, from `GET https://api.indstocks.com/order-book` and
`GET https://api.indstocks.com/trade-book?segment=`.

The API client unwraps INDstocks' `data`. An order-book row, measured on an open after-market order on
2026-09-13, carries `id`, `exch_order_id` (blank until the exchange has it), `status` (`O-PENDING` for an
order not yet at the exchange) and `remarks`, `security_id` - the token unified.broker_mappings stores -
and `name`, the company name rather than a trading symbol, on `exchange` in `segment` (`EQUITY` or
`DERIVATIVE`), `txn_type`, `product`, `order_type`, `validity`, `requested_qty`, `traded_qty`,
`requested_price`, `traded_price`, `sl_trigger_price`, `created_at`, `updated_at` and `remarks`, the tag the
order was placed with. With no trading symbol, `tradingsymbol` is the resolved instrument's.

The trade book is asked per segment, `EQUITY` and `DERIVATIVE`, both at once, and answers `null` when empty.
INDstocks publishes no trade-book schema and no trade has been seen, so its fields are an unconfirmed reading -
`fill_id`, `order_id`, `exch_order_id`, `security_id`, `exchange`, `txn_type`, `product`, `quantity`, `price` and
`trade_date_time` - and the likeliest of any broker's to need correcting.

**Writing.** An order is placed with `POST /order` and a JSON body of `txn_type`, `exchange`, `segment`,
`product` (`CNC`, `INTRADAY`, `MARGIN`), `order_type`, `validity`, `security_id`, `qty`, `limit_price`, `is_amo`,
`remarks` for the tag, and `algo_id`, the fixed identifier the exchanges' framework for API orders requires -
`99999` on NSE and `9999999999999999` on BSE. INDstocks takes only market and limit orders, and answers with
`order_id`. A modification is `POST /order/modify` and may change only the quantity and limit price; a
cancellation is `POST /order/cancel` with the order id and segment, which cancelled a live after-market order on
2026-09-13. A refusal in a successful response carries a `status` other than `success`.
"""

from concurrent.futures import ThreadPoolExecutor

from unified_broker_interface.utilities.broker_holdings.indmoney import IndmoneyHoldingsSource
from unified_broker_interface.utilities.broker_orders.base import (ORDER_TYPES, PRODUCTS, STATUSES, TRANSACTION_TYPES,
                                                                   VALIDITIES, BrokerOrdersSource, OrdersUnavailable,
                                                                   normalize, number, order, order_venue, text, trade)

ORDERS_URL = "https://api.indstocks.com/order-book"
TRADES_URL = "https://api.indstocks.com/trade-book"

PLACE_URL = "https://api.indstocks.com/order"
MODIFY_URL = "https://api.indstocks.com/order/modify"
CANCEL_URL = "https://api.indstocks.com/order/cancel"

SEGMENT_CODES = {("nse", "cash"): "EQUITY", ("bse", "cash"): "EQUITY", ("nse", "derivative"): "DERIVATIVE",
                 ("bse", "derivative"): "DERIVATIVE"}
PRODUCT_CODES = {"CNC": "CNC", "MIS": "INTRADAY", "NRML": "MARGIN"}
ALGO_IDENTIFIERS = {"nse": "99999", "bse": "9999999999999999"}

# The words in INDstocks' error types that mean a write was refused, lowercased.
REJECTION_MARKERS = ("validation", "order", "insufficient", "invalid", "margin")

TRADE_SEGMENTS = ("EQUITY", "DERIVATIVE")

# INDstocks' segments to the kind of instrument traded there.
SEGMENT_KINDS = {"EQUITY": "cash", "DERIVATIVE": "derivative"}

def _venue(row):
    """
    An INDstocks row's canonical exchange and kind, from its exchange and segment.
    """
    exchange = str(row.get("exchange") or "").lower() or None
    return (exchange, SEGMENT_KINDS.get(str(row.get("segment") or "").upper(), "cash"))

class IndmoneyOrdersSource(BrokerOrdersSource):
    """
    Reads INDmoney orders and trades.
    """

    BROKER_NAME = "indmoney"
    WRITES_ENABLED = True
    ORDER_TYPES_SUPPORTED = ("MARKET", "LIMIT")
    MODIFIABLE_FIELDS = ("quantity", "price")

    def _get(self, client, url, name, parameters=None):
        data = (client.get(url=url, params=parameters, timeout=self.TIMEOUT_SECONDS) or {}).get("data")
        if data is None:
            return []
        if not isinstance(data, list):
            raise OrdersUnavailable(f"INDstocks answered the {name} request without a {name}: {str(data)[:200]}")
        return data

    def fetch_orders(self, client):
        return self._get(client, ORDERS_URL, "order book")

    def fetch_trades(self, client):
        with ThreadPoolExecutor(max_workers=len(TRADE_SEGMENTS), thread_name_prefix="indmoney-trades") as pool:
            futures = {segment: pool.submit(self._get, client, TRADES_URL, "trade book", {"segment": segment})
                       for segment in TRADE_SEGMENTS}
        rows = []
        for segment, future in futures.items():
            for row in future.result():
                if isinstance(row, dict):
                    rows.append({"segment": segment, **row})
        return rows

    def normalize_order(self, row):
        return order(
            self.BROKER_NAME, row.get("exchange"), _venue(row),
            order_id=text(row.get("id")),
            exchange_order_id=text(row.get("exch_order_id")),
            status=normalize(row.get("status"), STATUSES),
            instrument_token=text(row.get("security_id")),
            transaction_type=normalize(row.get("txn_type"), TRANSACTION_TYPES),
            product=normalize(row.get("product"), PRODUCTS),
            order_type=normalize(row.get("order_type"), ORDER_TYPES),
            validity=normalize(row.get("validity"), VALIDITIES),
            quantity=number(row.get("requested_qty"), int),
            filled_quantity=number(row.get("traded_qty"), int),
            pending_quantity=(number(row.get("requested_qty"), int) or 0) - (number(row.get("traded_qty"), int) or 0),
            price=number(row.get("requested_price")),
            trigger_price=number(row.get("sl_trigger_price")),
            average_price=number(row.get("traded_price")),
            order_timestamp=row.get("created_at"),
            exchange_timestamp=row.get("updated_at"),
            tag=row.get("remarks") or None,
        )

    def normalize_trade(self, row):
        return trade(
            self.BROKER_NAME, row.get("exchange"), _venue(row),
            trade_id=text(row.get("fill_id") or row.get("trade_id")),
            order_id=text(row.get("order_id") or row.get("id")),
            exchange_order_id=text(row.get("exch_order_id")),
            instrument_token=text(row.get("security_id")),
            transaction_type=normalize(row.get("txn_type"), TRANSACTION_TYPES),
            product=normalize(row.get("product"), PRODUCTS),
            quantity=number(row.get("quantity") or row.get("traded_qty"), int),
            price=number(row.get("price") or row.get("traded_price")),
            trade_timestamp=row.get("trade_date_time") or row.get("created_at"),
        )

    is_authentication_error = IndmoneyHoldingsSource.is_authentication_error

    def build_place(self, order_request, identity, handle):
        body = {
            "txn_type": order_request["transaction_type"],
            "exchange": identity["exchange"].upper(),
            "segment": order_venue(self.BROKER_NAME, identity, SEGMENT_CODES),
            "product": PRODUCT_CODES[order_request["product"]],
            "order_type": order_request["order_type"],
            "validity": order_request["validity"],
            "security_id": str(handle["broker_token"]),
            "qty": order_request["quantity"],
            "algo_id": ALGO_IDENTIFIERS[identity["exchange"]],
            "limit_price": float(order_request["price"] or 0),
            "is_amo": order_request["after_market"],
        }
        if order_request["tag"]:
            body["remarks"] = order_request["tag"]
        return {"method": "POST", "url": PLACE_URL, "json": body}

    def build_modify(self, row, changes):
        values = self.modified_values(row, changes)
        return {"method": "POST", "url": MODIFY_URL, "json": {
            "order_id": str(row["id"]),
            "segment": row.get("segment") or "EQUITY",
            "qty": values["quantity"],
            "limit_price": float(values["price"] or 0),
        }}

    def build_cancel(self, row):
        return {"method": "POST", "url": CANCEL_URL,
                "json": {"order_id": str(row["id"]), "segment": row.get("segment") or "EQUITY"}}

    def written_order_id(self, response):
        data = (response or {}).get("data")
        return text(data.get("order_id")) if isinstance(data, dict) else None

    def write_error(self, response):
        data = (response or {}).get("data")
        if isinstance(data, dict) and str(data.get("status", "success")).lower() not in ("success",):
            return str(data.get("message") or data.get("error") or f"status {data.get('status')}")
        return None

    def is_rejection(self, exception):
        code = str(getattr(exception, "code", "") or "").lower()
        return any(marker in code for marker in REJECTION_MARKERS)
