"""
Placing, modifying and cancelling orders for `/api/orders/place`, `/modify` and `/cancel`.

**Placing.** The order is read and checked in the shared vocabulary, the instrument resolved - by
`instrument_id`, or by exchange, segment and identity fields as `/api/instruments` takes them - and the brokers
ranked by `routing.py`. The order goes to the first of them whose module can build it; one that cannot - a
segment or order it does not take - is reported in `routing` and the next is tried. The quantity must then be
whole lots at that broker and the prices whole ticks of the instrument's tick in rupees.

**Modifying and cancelling** name the order by `broker` and `order_id`, as the order book answers them. The
order's row is read from that broker's order book first, because every broker needs something the id alone does
not carry; an order the book does not hold is `404`, and one no longer pending or open is `409`.

**Dry run.** With `dry_run` true the call is built and returned - method, URL and body; the session headers
the API client adds are not shown - and nothing is sent.

**Outcome.** A sent write ends one of three ways, and none is retried:

- `accepted`, with the broker's order id;
- `rejected`, a refusal that settles it - the order was not placed, modified or cancelled;
- `unknown`, when the call timed out, the connection dropped or the broker failed, so it may have reached the
  exchange. Look for the order in `/api/orders/details`, by `tag` for a placement, before sending it again.

The one call made twice is a write refused for a dead session when another process has already stored a newer
session: that refusal is certain, so the write is sent once more with it. With no newer session the broker's
`<broker>-login.service` is started and the write is rejected, nothing sent; see `broker_quotes/utilities/clients.py`. Every write takes a slot in the broker's order limits
first, and is refused with `429` when there is none. Every write is logged with the broker's response.
"""

import re
from decimal import Decimal, InvalidOperation

import requests

from unified_broker_interface.utilities.broker_orders.utilities.vocabulary import (ORDER_TYPES, PRODUCTS, TRANSACTION_TYPES,
                                                                                VALIDITIES, normalize)
from unified_broker_interface.utilities.broker_orders.base import MODIFIABLE_STATUSES, UnsupportedOrder
from unified_broker_interface.utilities.broker_orders.utilities.rate_limits import RateLimited, take_slot
from unified_broker_interface.utilities.broker_orders.utilities.routing import OrderRouter, record_placed
from unified_broker_interface.utilities.broker_orders.utilities.service import SOURCES
from unified_broker_interface.utilities.broker_quotes.utilities.clients import SessionUnavailable, client_for, relogin, session_marker
from unified_broker_interface.utilities.instrument_identity import RequestError, parse_instrument
from utilities.configurations import get_logger

logger = get_logger("rest_api.order_writes")

# The orders modules that place, modify and cancel.
WRITE_SOURCES = {broker: source for broker, source in SOURCES.items() if source.WRITES_ENABLED}

# The brokers whose mapped tick size is in rupees in every segment. The mapping rules convert Dhan's, Kotak's,
# INDmoney's, Stoxkart's and Groww's paise to rupees only in the tradeable segments, and their indices and
# uncategorised rows are still in paise, so a price is checked against one of these brokers' tick for the
# instrument, whichever broker the order goes to.
RUPEE_TICK_BROKERS = ("zerodha", "fyers", "groww", "shoonya", "wisdom_capital")

SIDES = ("BUY", "SELL")
PRODUCT_CHOICES = ("CNC", "MIS", "NRML")
ORDER_TYPE_CHOICES = ("MARKET", "LIMIT", "SL", "SL-M")
VALIDITY_CHOICES = ("DAY", "IOC")
PRICED_TYPES = ("LIMIT", "SL")
TRIGGERED_TYPES = ("SL", "SL-M")

INSTRUMENT_FIELDS = ("instrument_id", "exchange", "segment", "symbol", "underlying_symbol", "expiry_date",
                     "strike_price", "option_type")

TAG_PATTERN = re.compile(r"^[A-Za-z0-9]{1,20}$")

# The HTTP status each outcome is answered with.
OUTCOME_STATUSES = {"accepted": 200, "rejected": 422, "unknown": 504}

def _flag(body, name):
    """
    A true or false field, false when absent.
    """
    value = body.get(name, False)
    if isinstance(value, bool):
        return value
    if str(value).strip().lower() in ("true", "1", "yes"):
        return True
    if str(value).strip().lower() in ("false", "0", "no", ""):
        return False
    raise RequestError(f"{name} must be true or false")

def _choice(body, name, table, choices, default=None):
    """
    A field in the shared vocabulary, read through its table so `buy` and `Buy` are `BUY`.
    """
    value = body.get(name)
    if value in (None, ""):
        if default is None:
            raise RequestError(f"{name} is required, one of {', '.join(choices)}")
        return default
    normalized = normalize(value, table)
    if normalized not in choices:
        raise RequestError(f"{name} must be one of {', '.join(choices)}")
    return normalized

def _quantity(body, name, minimum, required=True):
    """
    A whole number field no smaller than `minimum`, or None when optional and absent.
    """
    value = body.get(name)
    if value in (None, ""):
        if required:
            raise RequestError(f"{name} is required")
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        raise RequestError(f"{name} must be a whole number")
    if parsed != parsed.to_integral_value() or parsed < minimum:
        raise RequestError(f"{name} must be a whole number of at least {minimum}")
    return int(parsed)

def _amount(body, name):
    """
    A price field as a Decimal no smaller than zero, or None when absent.
    """
    value = body.get(name)
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        raise RequestError(f"{name} must be a number")
    if parsed < 0 or not parsed.is_finite():
        raise RequestError(f"{name} must not be negative")
    return parsed

def _check_prices(order_type, price, trigger_price):
    """
    Refuse a price or trigger price the order type needs and lacks, or does not take and has.
    """
    if order_type in PRICED_TYPES and not price:
        raise RequestError(f"a {order_type} order needs a price")
    if order_type not in PRICED_TYPES and price:
        raise RequestError(f"a {order_type} order takes no price")
    if order_type in TRIGGERED_TYPES and not trigger_price:
        raise RequestError(f"a {order_type} order needs a trigger_price")
    if order_type not in TRIGGERED_TYPES and trigger_price:
        raise RequestError(f"a {order_type} order takes no trigger_price")

def _multiple_of(value, step):
    """
    Whether a value is a whole number of steps.
    """
    return (value / step) == (value / step).to_integral_value()

def _broker_and_order(body):
    """
    The `broker` and `order_id` a modification or cancellation names, and the broker's orders module.
    """
    broker = str(body.get("broker") or "").strip().lower()
    order_id = str(body.get("order_id") or "").strip()
    if not broker or not order_id:
        raise RequestError("broker and order_id are required")
    if broker not in WRITE_SOURCES:
        if broker in SOURCES:
            reason = SOURCES[broker].WRITES_BLOCKED_REASON or "is not written to through this API yet"
            raise RequestError(f"{broker} orders cannot be modified or cancelled here: {broker} {reason}", 501)
        raise RequestError(f"unknown broker {broker}")
    return broker, order_id, WRITE_SOURCES[broker]

def _failure(source, exception):
    """
    The outcome and message of a write whose call raised.
    """
    message = getattr(exception, "message", None) or str(exception)
    if source.is_rejection(exception):
        return "rejected", str(message)[:300]
    if isinstance(exception, requests.exceptions.ConnectTimeout):
        return "rejected", f"could not connect to the broker, so nothing was sent: {str(exception)[:200]}"
    return "unknown", f"{type(exception).__name__}: {str(message)[:300]}"

class OrderWriteService:
    """
    Places, modifies and cancels orders.

    Attributes:
        cache (redis.Redis): The shared Redis client.
        mapping_cache (MappingCache): The worker's mapping cache, for order handles.
        catalogue (InstrumentCatalogue): Resolves the instrument an order names.
        router (OrderRouter): Chooses the broker an order is placed at.
    """

    def __init__(self, cache, mapping_cache, catalogue, quotes, read_available_balance):
        """
        - `cache` is the shared Redis client.
        - `mapping_cache` is the worker's `MappingCache`.
        - `catalogue` is the worker's `InstrumentCatalogue`.
        - `quotes` is the worker's `QuoteService`.
        - `read_available_balance` takes a broker name to its live available balance.
        """
        self.cache = cache
        self.mapping_cache = mapping_cache
        self.catalogue = catalogue
        self.router = OrderRouter(cache, SOURCES, read_available_balance, quotes)

    def place(self, body):
        """
        Place an order at the broker the router chooses, and the answer with its HTTP status.

        - `body` is the request's fields.
        """
        order_request = self._order_request(body)
        dry_run = _flag(body, "dry_run")
        instrument_args = {field: str(body[field]) for field in INSTRUMENT_FIELDS if body.get(field) not in (None, "")}
        identity, mapping_date, _ = self.catalogue.resolve(parse_instrument(instrument_args))
        instrument_id = str(identity["instrument_id"])
        handles = self.mapping_cache.order_handles_for_instruments([instrument_id], mapping_date).get(instrument_id, {})

        candidates, routing = self.router.choose(order_request, identity, mapping_date, handles)
        decisions = {decision.get("broker"): decision for decision in routing}
        broker = call = None
        for candidate in candidates:
            try:
                call = WRITE_SOURCES[candidate].build_place(order_request, identity, handles[candidate])
            except UnsupportedOrder as exception:
                decisions[candidate].update({"eligible": False, "reason": str(exception)})
                continue
            broker = candidate
            decisions[candidate]["chosen"] = True
            break
        if broker is None:
            return {"error": "no broker can take this order", "instrument_id": instrument_id, "routing": routing}, 503
        source = WRITE_SOURCES[broker]
        self._check_handle(order_request, handles, broker)

        answer = {"broker": broker, "instrument_id": instrument_id, "tag": call.pop("tag", order_request["tag"]),
                  "routing": routing}
        if dry_run:
            return {**answer, "dry_run": True, "request": call}, 200
        outcome, order_id, message = self._send(broker, source, call, "place")
        if outcome == "accepted":
            record_placed(self.cache, broker)
        return {**answer, "outcome": outcome, "order_id": order_id, "status_message": message}, OUTCOME_STATUSES[outcome]

    def modify(self, body):
        """
        Modify a pending or open order, and the answer with its HTTP status.

        - `body` is the request's fields: `broker`, `order_id` and the fields to change.
        """
        broker, order_id, source = _broker_and_order(body)
        dry_run = _flag(body, "dry_run")
        changes = {
            "quantity": _quantity(body, "quantity", 1, required=False),
            "disclosed_quantity": _quantity(body, "disclosed_quantity", 0, required=False),
            "price": _amount(body, "price"),
            "trigger_price": _amount(body, "trigger_price"),
            "order_type": _choice(body, "order_type", ORDER_TYPES, ORDER_TYPE_CHOICES) if body.get("order_type") else None,
            "validity": _choice(body, "validity", VALIDITIES, VALIDITY_CHOICES) if body.get("validity") else None,
        }
        changes = {field: value for field, value in changes.items() if value is not None}
        if not changes:
            raise RequestError("give at least one of quantity, price, trigger_price, order_type, validity, disclosed_quantity")
        refused = [field for field in changes if field not in source.MODIFIABLE_FIELDS]
        if refused:
            raise RequestError(f"{broker} does not allow {', '.join(refused)} to be modified")
        if changes.get("order_type") and changes["order_type"] not in source.ORDER_TYPES_SUPPORTED:
            raise RequestError(f"{broker} does not take {changes['order_type']} orders")

        row, current = self._pending_order(broker, source, order_id)
        self._check_modified_prices(changes, current)
        call = source.build_modify(row, changes)
        answer = {"broker": broker, "order_id": order_id}
        if dry_run:
            return {**answer, "dry_run": True, "order": current, "request": call}, 200
        outcome, _, message = self._send(broker, source, call, "modify")
        return {**answer, "outcome": outcome, "status_message": message}, OUTCOME_STATUSES[outcome]

    def cancel(self, body):
        """
        Cancel a pending or open order, and the answer with its HTTP status.

        - `body` is the request's fields: `broker` and `order_id`.
        """
        broker, order_id, source = _broker_and_order(body)
        dry_run = _flag(body, "dry_run")
        row, current = self._pending_order(broker, source, order_id)
        call = source.build_cancel(row)
        answer = {"broker": broker, "order_id": order_id}
        if dry_run:
            return {**answer, "dry_run": True, "order": current, "request": call}, 200
        outcome, _, message = self._send(broker, source, call, "cancel")
        return {**answer, "outcome": outcome, "status_message": message}, OUTCOME_STATUSES[outcome]

    def _order_request(self, body):
        """
        A placement's order fields, checked, in the shared vocabulary.
        """
        order_request = {
            "transaction_type": _choice(body, "transaction_type", TRANSACTION_TYPES, SIDES),
            "product": _choice(body, "product", PRODUCTS, PRODUCT_CHOICES),
            "order_type": _choice(body, "order_type", ORDER_TYPES, ORDER_TYPE_CHOICES),
            "validity": _choice(body, "validity", VALIDITIES, VALIDITY_CHOICES, "DAY"),
            "quantity": _quantity(body, "quantity", 1),
            "price": _amount(body, "price"),
            "trigger_price": _amount(body, "trigger_price"),
            "disclosed_quantity": _quantity(body, "disclosed_quantity", 0, required=False) or 0,
            "after_market": _flag(body, "after_market"),
            "tag": str(body["tag"]).strip() if body.get("tag") not in (None, "") else None,
        }
        _check_prices(order_request["order_type"], order_request["price"], order_request["trigger_price"])
        if order_request["disclosed_quantity"] > order_request["quantity"]:
            raise RequestError("disclosed_quantity cannot be more than quantity")
        if order_request["tag"] is not None and not TAG_PATTERN.match(order_request["tag"]):
            raise RequestError("tag must be 1 to 20 letters and digits")
        return order_request

    def _check_modified_prices(self, changes, current):
        """
        Refuse a modification that leaves the order without a price or trigger price its type needs, or gives
        one its type does not take.
        """
        order_type = changes.get("order_type") or current["order_type"]
        price = changes["price"] if "price" in changes else Decimal(str(current["price"] or 0))
        trigger_price = changes["trigger_price"] if "trigger_price" in changes else Decimal(str(current["trigger_price"] or 0))
        if order_type in PRICED_TYPES and not price:
            raise RequestError(f"a {order_type} order needs a price")
        if order_type in TRIGGERED_TYPES and not trigger_price:
            raise RequestError(f"a {order_type} order needs a trigger_price")
        if order_type not in PRICED_TYPES and changes.get("price"):
            raise RequestError(f"a {order_type} order takes no price")
        if order_type not in TRIGGERED_TYPES and changes.get("trigger_price"):
            raise RequestError(f"a {order_type} order takes no trigger_price")

    def _check_handle(self, order_request, handles, broker):
        """
        Refuse a quantity that is not whole lots at the chosen broker, or a price that is not whole ticks of the
        instrument's tick in rupees.
        """
        handle = handles[broker]
        lot_size = Decimal(handle["lot_size"]) if handle.get("lot_size") else None
        if lot_size and lot_size > 0 and not _multiple_of(Decimal(order_request["quantity"]), lot_size):
            raise RequestError(f"quantity must be a whole number of lots of {lot_size.normalize()}")
        ticks = [handles[name]["tick_size"] for name in RUPEE_TICK_BROKERS if handles.get(name, {}).get("tick_size")]
        tick_size = Decimal(ticks[0]) if ticks else None
        for field in ("price", "trigger_price"):
            if tick_size and tick_size > 0 and order_request[field] and not _multiple_of(order_request[field], tick_size):
                raise RequestError(f"{field} must be a whole number of ticks of {tick_size.normalize()}")

    def _pending_order(self, broker, source, order_id):
        """
        An order's raw row and its normalized form, refusing an order the book does not hold or that is closed.
        """
        client = client_for(broker)
        session = session_marker(client)
        try:
            row = source.find_order(client, order_id)
        except Exception as exception:
            if not source.is_authentication_error(exception):
                raise RequestError(f"{broker} order book could not be read: {type(exception).__name__}: {str(exception)[:200]}", 502)
            try:
                relogin(broker, client, session)
            except SessionUnavailable as unavailable:
                raise RequestError(str(unavailable), 503)
            row = source.find_order(client, order_id)
        if row is None:
            raise RequestError(f"{broker} has no order {order_id} in today's order book", 404)
        current = source.normalize_order(row)
        current.pop("venue", None)
        if current["status"] not in MODIFIABLE_STATUSES:
            raise RequestError(f"{broker} order {order_id} is {current['status']} and can no longer be changed", 409)
        return row, current

    def _send(self, broker, source, call, action):
        """
        Send a write once - twice only after a refused session - and its outcome, order id and message.
        """
        try:
            take_slot(self.cache, broker)
        except RateLimited as exception:
            raise RequestError(str(exception), 429)
        client = client_for(broker)
        session = session_marker(client)
        try:
            response = source.send(client, call)
        except Exception as exception:
            if not source.is_authentication_error(exception):
                outcome, message = _failure(source, exception)
                logger.warning(f"{broker} {action} {outcome}: {message}; request {call}")
                return outcome, None, message
            try:
                relogin(broker, client, session)
            except Exception as login_exception:
                message = f"the session was refused and no newer one is stored yet, so nothing was sent: {login_exception}"
                logger.warning(f"{broker} {action} rejected: {message}")
                return "rejected", None, message
            try:
                response = source.send(client, call)
            except Exception as retry_exception:
                outcome, message = _failure(source, retry_exception)
                logger.warning(f"{broker} {action} {outcome} after logging in again: {message}; request {call}")
                return outcome, None, message

        error = source.write_error(response)
        if error:
            logger.warning(f"{broker} {action} rejected: {error}; request {call}; response {response}")
            return "rejected", None, error
        order_id = source.written_order_id(response)
        if order_id is None:
            logger.warning(f"{broker} {action} answered without an order id; request {call}; response {response}")
            return "unknown", None, "the broker answered without an order id"
        logger.info(f"{broker} {action} accepted: order {order_id}; request {call}; response {response}")
        return "accepted", order_id, None
