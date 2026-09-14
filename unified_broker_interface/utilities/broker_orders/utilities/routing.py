"""
Choosing the broker an order is placed at. The caller never names one.

**Candidates.** Every broker that carries the instrument - has an order handle for it in the mapping - and
places orders through this API, takes the order type, and has room in its order limits.

**Funds.** A delivery buy has to be paid for in full, so a broker whose live available balance is below the
order's value is left out, and so is one whose balance cannot be read at that moment. The value is the price
times the quantity, and for a market or stop-loss market order the unified quote's last price with 1% added,
so a small move does not let an order through that its broker will refuse. When no price can be had at all
the check is skipped rather than blocking the order. Intraday, carry-forward and derivative orders need only
margin, which is not known without each broker's margin calculator, so they are not checked here and the
broker's own risk checks decide.

**Ranking.** The candidates left are ranked by how many orders this API has placed at each today, fewest
first, so orders spread across brokers, and then by a fixed preference.

Every broker considered is reported with whether it was eligible and why not, so a routing decision can always
be read back.
"""

from datetime import datetime
from decimal import Decimal

from unified_broker_interface.utilities.broker_orders.utilities.rate_limits import has_room
from unified_broker_interface.utilities.instrument_identity import INDIA
from utilities.configurations import get_logger

logger = get_logger("rest_api.order_routing")

# The order brokers are preferred in when they have placed as many orders today.
BROKER_PREFERENCE = ["zerodha", "dhan", "kotak", "flattrade", "shoonya", "wisdom_capital", "groww", "indmoney",
                     "fyers", "stoxkart"]

# How far a market order's value is padded above the last price for the funds check.
MARKET_PRICE_PADDING = Decimal("1.01")

PLACED_KEY_PREFIX = "unified:orders:placed"

def _placed_key(broker):
    """
    The Redis counter of orders placed at a broker today, India time.
    """
    return f"{PLACED_KEY_PREFIX}:{broker}:{datetime.now(INDIA).date().isoformat()}"

def placed_today(cache, broker):
    """
    How many orders this API has placed at a broker today.
    """
    return int(cache.get(_placed_key(broker)) or 0)

def record_placed(cache, broker):
    """
    Count one order placed at a broker today; the counter lapses after two days.
    """
    key = _placed_key(broker)
    cache.incr(key)
    cache.expire(key, 2 * 86400)

class OrderRouter:
    """
    Chooses the broker for an order.

    Attributes:
        cache (redis.Redis): The shared Redis client, for rate limits and order counts.
        sources (dict): The orders modules that write, by broker name.
        read_available_balance (callable): A broker name to its live available balance.
        quotes (QuoteService): The worker's quote service, for a market order's price.
    """

    def __init__(self, cache, sources, read_available_balance, quotes):
        self.cache = cache
        self.sources = sources
        self.read_available_balance = read_available_balance
        self.quotes = quotes

    def choose(self, order_request, identity, mapping_date, handles):
        """
        The eligible brokers in the order they are preferred, and every broker's verdict.

        The caller places at the first one that can build the order, and marks it chosen.

        - `order_request` is the validated order.
        - `identity` is the instrument's identity.
        - `mapping_date` is the mapping date it was resolved on.
        - `handles` are the brokers' order handles for it, by broker name.
        """
        decisions = []
        eligible = []
        value = None
        needs_funds = order_request["product"] == "CNC" and order_request["transaction_type"] == "BUY"
        if needs_funds:
            value = self._order_value(order_request, identity, mapping_date)

        for broker in sorted(set(handles) | set(self.sources), key=self._preference):
            source = self.sources.get(broker)
            reason = None
            if source is None or not source.WRITES_ENABLED:
                reason = getattr(source, "WRITES_BLOCKED_REASON", None) or "does not place orders through this API"
            elif order_request["after_market"] and not source.SUPPORTS_AFTER_MARKET:
                reason = "does not take after-market orders"
            elif broker not in handles:
                reason = "does not carry the instrument"
            elif order_request["order_type"] not in source.ORDER_TYPES_SUPPORTED:
                reason = f"does not take {order_request['order_type']} orders"
            elif not has_room(self.cache, broker):
                reason = "is at its order limit"
            elif needs_funds and value is not None:
                reason = self._funds_reason(broker, value)
            decision = {"broker": broker, "eligible": reason is None}
            if reason:
                decision["reason"] = reason
            else:
                decision["orders_today"] = placed_today(self.cache, broker)
                eligible.append(decision)
            decisions.append(decision)

        if needs_funds:
            note = f"order value {value}" if value is not None else "no price to value the order at; funds not checked"
            decisions.append({"funds_check": note})
        eligible.sort(key=lambda decision: (decision["orders_today"], self._preference(decision["broker"])))
        return [decision["broker"] for decision in eligible], decisions

    def _preference(self, broker):
        return BROKER_PREFERENCE.index(broker) if broker in BROKER_PREFERENCE else len(BROKER_PREFERENCE)

    def _order_value(self, order_request, identity, mapping_date):
        """
        What an order will cost in full, or None when there is no price to value it at.
        """
        quantity = Decimal(order_request["quantity"])
        if order_request["order_type"] in ("LIMIT", "SL"):
            return quantity * Decimal(str(order_request["price"]))
        try:
            last_price = self.quotes.quote(identity, mapping_date).get("last_price")
        except Exception as exception:
            logger.warning(f"no quote to value a market order at: {type(exception).__name__}: {exception}")
            return None
        if last_price is None:
            return None
        return (quantity * Decimal(str(last_price)) * MARKET_PRICE_PADDING).quantize(Decimal("0.01"))

    def _funds_reason(self, broker, value):
        """
        Why a broker cannot pay for an order of this value, or None when it can.
        """
        try:
            available = Decimal(str(self.read_available_balance(broker)))
        except Exception as exception:
            logger.warning(f"{broker} funds could not be read for routing: {type(exception).__name__}: {exception}")
            return "funds could not be read"
        if available < value:
            return f"available balance {available} is below the order value {value}"
        return None
