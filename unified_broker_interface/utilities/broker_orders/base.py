"""
What a broker's orders module provides, and the rows every module builds.

**An order** is the project's order contract: `empty_order_update` from `utilities/vocabulary.py`, filled in
and mapped onto the shared vocabulary - `BUY`/`SELL`, `CNC`/`MIS`/`NRML`, `MARKET`/`LIMIT`/`SL`/`SL-M`, and a
status of `PENDING`, `OPEN`, `COMPLETE`, `CANCELLED`, `REJECTED` or `EXPIRED`, with anything unrecognised
passed through upper-cased. The API answers without `raw` and `received_at`, and with the order's
`instrument_id`.

**A trade** is one fill, in the same vocabulary: which order it filled, the instrument, side and product,
the quantity filled, the price it filled at and their product as `value`.

Both carry a private `venue`, the canonical exchange and kind of instrument read from the broker's own
exchange code, which the service resolves the instrument with and removes before answering. `exchange`
itself stays the broker's own code, as the order contract has it.

**Writing.** A broker that places, modifies and cancels sets `WRITES_ENABLED` and writes three pure build
methods, which describe one HTTP call as `{"method", "url", "form" or "json"}` without making it - so every
order type and segment can be built and read field by field with no token, no network and no market, and a
dry run can show exactly what would be sent. Modify and cancel are built from the order's own row in the
broker's order book, read just before, because every broker needs something the order id alone does not
carry. The API client adds the session headers when the call is sent.
"""

from unified_broker_interface.utilities.broker_orders.utilities.vocabulary import (ORDER_TYPES, PRODUCTS, STATUSES,
                                                                                TRANSACTION_TYPES, VALIDITIES,
                                                                                empty_order_update, normalize)
from unified_broker_interface.utilities.broker_positions.base import venue

__all__ = ["BrokerOrdersSource", "OrdersUnavailable", "UnsupportedOrder", "empty_trade", "number", "order", "text",
           "trade", "venue", "normalize", "ORDER_TYPES", "PRODUCTS", "STATUSES", "TRANSACTION_TYPES", "VALIDITIES",
           "MODIFIABLE_STATUSES", "instrument_kind", "order_venue"]

# The statuses an order can still be modified or cancelled in.
MODIFIABLE_STATUSES = ("PENDING", "OPEN")

def order_venue(broker, identity, codes):
    """
    A broker's own exchange or segment code for an order on an instrument.

    Commodity and currency derivatives are refused at every broker for now: brokers count their order quantity
    in lots where every other order is in units, and that has not been confirmed for any of them.

    - `broker` is the broker name, for the message.
    - `identity` is the instrument's identity.
    - `codes` maps `(exchange, kind)` to the broker's code.

    Raises `UnsupportedOrder` for a kind or exchange the broker has no code for.
    """
    kind = instrument_kind(identity)
    if kind in ("commodity", "currency"):
        raise UnsupportedOrder(f"{broker} orders are not sent for {identity['segment']} yet: their quantity may be "
                               "counted in lots, which has not been confirmed")
    code = codes.get((identity["exchange"], kind))
    if code is None:
        raise UnsupportedOrder(f"{broker} takes no orders for {identity['segment']}")
    return code

def instrument_kind(identity):
    """
    What kind of instrument an identity is, as an order names it: `cash`, `derivative` (equity, index or fixed
    income futures and options), `currency` or `commodity`.

    - `identity` is the instrument's identity.
    """
    bare = identity["segment"].split("_", 1)[1]
    if bare.startswith("commodit"):
        return "commodity"
    if bare.startswith("currenc") and identity["shape"] != "security":
        return "currency"
    return "cash" if identity["shape"] == "security" else "derivative"

# The order contract's fields the API does not answer with.
FEED_ONLY_FIELDS = ("raw", "received_at")

class UnsupportedOrder(Exception):
    """
    The broker cannot take this order as asked - an order type, segment or field it does not support, or one
    this API does not yet send to it.
    """

class OrdersUnavailable(Exception):
    """
    The broker answered, but not with its order or trade book - an error carried in a successful response,
    or a body of the wrong shape.
    """

def number(value, cast=float):
    """
    A broker's field as a number, or None when it is blank, a placeholder or not a number.

    - `value` is the field as the broker sent it.
    - `cast` is the type wanted, `float` or `int`.
    """
    if value is None or value == "" or value == "NA":
        return None
    try:
        return cast(float(value)) if cast is int else cast(value)
    except (TypeError, ValueError):
        return None

def text(value):
    """
    A broker's identifier or message as a string, or None when it is blank or zero.

    - `value` is the field as the broker sent it.
    """
    if value is None or value in ("", 0, "0"):
        return None
    return str(value)

def order(broker, exchange_code=None, venue_code=None, **fields):
    """
    One order in the order contract, with every contract field present.

    - `broker` is the broker name.
    - `exchange_code` is the broker's own exchange or segment code, answered as `exchange`.
    - `venue_code` is the code the venue is read from, when it is not `exchange_code`, or a ready
      `(exchange, kind)` pair.
    - `fields` are the contract's other fields, already normalized.
    """
    row = empty_order_update(broker)
    for field in FEED_ONLY_FIELDS:
        row.pop(field, None)
    row["instrument_id"] = None
    row["exchange"] = exchange_code
    row.update(fields)
    row["venue"] = venue_code if isinstance(venue_code, tuple) else venue(venue_code or exchange_code)
    return row

def empty_trade(broker):
    """
    One trade with every field present and unset.

    - `broker` is the broker name.
    """
    return {
        "broker": broker,
        "trade_id": None,
        "order_id": None,
        "exchange_order_id": None,
        "exchange_trade_id": None,
        "instrument_id": None,
        "instrument_token": None,
        "tradingsymbol": None,
        "exchange": None,
        "transaction_type": None,
        "product": None,
        "quantity": None,
        "price": None,
        "value": None,
        "trade_timestamp": None,
        "exchange_timestamp": None,
    }

def trade(broker, exchange_code=None, venue_code=None, **fields):
    """
    One trade, with every field present and `value` worked out from the quantity and price.

    - `broker` is the broker name.
    - `exchange_code` is the broker's own exchange or segment code, answered as `exchange`.
    - `venue_code` is the code the venue is read from, when it is not `exchange_code`, or a ready
      `(exchange, kind)` pair.
    - `fields` are the trade's other fields, already normalized.
    """
    row = empty_trade(broker)
    row["exchange"] = exchange_code
    row.update(fields)
    if row["quantity"] is not None and row["price"] is not None:
        row["value"] = round(row["quantity"] * row["price"], 2)
    row["venue"] = venue_code if isinstance(venue_code, tuple) else venue(venue_code or exchange_code)
    return row

class BrokerOrdersSource:
    """
    Reads one broker's order book and trade book from its REST API.

    Attributes:
        BROKER_NAME (str): The broker, as named in the `settings` collection and unified.broker_mappings.
        TIMEOUT_SECONDS (float): How long the broker may take to connect, and then to send each part of its
            answer, before a call is abandoned.
    """

    BROKER_NAME = None
    TIMEOUT_SECONDS = 5

    # Whether this broker places, modifies and cancels through the API.
    WRITES_ENABLED = False

    # Why a broker with a write build does not write, reported by the router and to a modify or cancel.
    WRITES_BLOCKED_REASON = None

    # Whether this broker takes after-market orders.
    SUPPORTS_AFTER_MARKET = True

    # How long a write may take before its outcome is unknown. Longer than a read, because a write that times
    # out may still have reached the exchange, and giving up early only makes that more likely.
    WRITE_TIMEOUT_SECONDS = 10

    # The order types this broker takes, in the shared vocabulary.
    ORDER_TYPES_SUPPORTED = ("MARKET", "LIMIT", "SL", "SL-M")

    # The fields a modification may change at this broker.
    MODIFIABLE_FIELDS = ("quantity", "price", "trigger_price", "order_type", "validity", "disclosed_quantity")

    def fetch_orders(self, client):
        """
        The rows of today's order book.

        - `client` is the broker's API client, whose `get`/`post` carry the session.

        Raises `OrdersUnavailable` when the broker answered without an order book, and lets the API client's
        own exceptions through. A day with no orders is an empty list, not an error.
        """
        raise NotImplementedError

    def fetch_trades(self, client):
        """
        The rows of today's trade book, raising and answering as `fetch_orders` does.

        - `client` is the broker's API client.
        """
        raise NotImplementedError

    def normalize_order(self, row):
        """
        One order-book row as an `order`.

        - `row` is one row `fetch_orders` returned.
        """
        raise NotImplementedError

    def normalize_trade(self, row):
        """
        One trade-book row as a `trade`.

        - `row` is one row `fetch_trades` returned.
        """
        raise NotImplementedError

    def is_authentication_error(self, exception):
        """
        Whether an exception means the session is dead, so logging in again is the remedy.

        - `exception` is what a fetch raised.
        """
        raise NotImplementedError

    def find_order(self, client, order_id):
        """
        The raw order-book row of one order, or None when the book does not hold it.

        - `client` is the broker's API client.
        - `order_id` is the broker's order id.
        """
        for row in self.fetch_orders(client):
            if isinstance(row, dict) and self.normalize_order(row)["order_id"] == str(order_id):
                return row
        return None

    def build_place(self, order_request, identity, handle):
        """
        The call that places an order, described and not made.

        - `order_request` is the validated order: `transaction_type`, `product`, `order_type`, `validity`,
          `quantity` in units, `price`, `trigger_price`, `disclosed_quantity`, `after_market` and `tag`.
        - `identity` is the instrument's identity.
        - `handle` is this broker's order handle for it: `broker_token`, `order_symbol`, `lot_size`, `tick_size`.

        Raises `UnsupportedOrder` when this broker cannot take the order.
        """
        raise NotImplementedError

    def build_modify(self, row, changes):
        """
        The call that modifies an order, described and not made.

        - `row` is the order's raw order-book row.
        - `changes` are the validated fields to change, in the shared vocabulary.
        """
        raise NotImplementedError

    def build_cancel(self, row):
        """
        The call that cancels an order, described and not made.

        - `row` is the order's raw order-book row.
        """
        raise NotImplementedError

    def modified_values(self, row, changes):
        """
        An order's modifiable values as they will stand after a modification: its current values from the order
        book, with the changes laid over them, in the shared vocabulary.

        For a broker that wants the whole order restated on every modification.

        - `row` is the order's raw order-book row.
        - `changes` are the validated fields to change.
        """
        current = self.normalize_order(row)
        values = {field: current.get(field) for field in
                  ("quantity", "price", "trigger_price", "order_type", "validity", "disclosed_quantity")}
        values.update({field: value for field, value in changes.items() if value is not None})
        return values

    def account_fields(self, client, request):
        """
        The request with any account identifier the body needs added from the broker's settings, which a pure
        build cannot see. The default adds nothing.

        - `client` is the broker's API client.
        - `request` is what a build method returned.
        """
        return request

    def send(self, client, request):
        """
        Make a described call through the broker's API client, which adds the session headers.

        - `client` is the broker's API client.
        - `request` is what a build method returned.
        """
        request = self.account_fields(client, request)
        call = {"POST": client.post, "PUT": client.put, "PATCH": client.patch, "DELETE": client.delete}[request["method"]]
        return call(url=request["url"], params=request.get("params"), data=request.get("form"),
                    json=request.get("json"), timeout=self.WRITE_TIMEOUT_SECONDS)

    def written_order_id(self, response):
        """
        The order id in a successful write's response, or None when the response carries none.

        - `response` is what `send` returned.
        """
        raise NotImplementedError

    def write_error(self, response):
        """
        The broker's message when a successful HTTP response is really a refusal, or None.

        - `response` is what `send` returned.
        """
        return None

    def is_rejection(self, exception):
        """
        Whether a failed write was refused outright by the broker, so the order certainly does not exist.

        Anything that is not a rejection and not a refused session - a timeout, a server error, a lost
        connection - leaves the write's outcome unknown.

        - `exception` is what `send` raised.
        """
        return False
