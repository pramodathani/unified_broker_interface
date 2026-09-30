"""Whether each broker has the free cash an order needs, decided from Redis and in-memory tables without calling a broker."""

import datetime
import decimal
import json
import threading

from unified_broker_interface.utilities.broker_selection.utilities.funds_reservations import (
    FundsReservations,
)
from unified_broker_interface.utilities.broker_selection.utilities.margin_estimate import (
    MarginEstimate,
)
from unified_broker_interface.utilities.broker_selection.utilities.order_legs import (
    OrderLegs,
)
from unified_broker_interface.utilities.broker_selection.utilities.priced_leg import (
    PricedLeg,
)

FUNDS_KEY = 'unified:portfolio:funds'
CURRENT_DATE_KEY = 'unified:catalogue:current_date'
QUOTES_KEY = 'unified:quotes:live'
FUNDS_TIME_FORMAT = '%Y-%m-%d %H:%M:%S.%f'
PENNY = decimal.Decimal('0.01')

LEG_PRICES_SCRIPT = """
local mapping_date = redis.call('GET', KEYS[1])
local function last_price(instrument_id)
    local quote = redis.call('HGET', KEYS[2], instrument_id)
    if not quote then
        return ''
    end
    local decoded_ok, decoded = pcall(cjson.decode, quote)
    if decoded_ok and type(decoded) == 'table' and type(decoded['last_price']) == 'number' then
        return tostring(decoded['last_price'])
    end
    return ''
end
local replies = {}
for index = 1, #ARGV do
    local identity = false
    local underlying_id = false
    if mapping_date then
        identity = redis.call('HGET', 'unified:catalogue:' .. mapping_date .. ':identity', ARGV[index])
        underlying_id = redis.call('HGET', 'unified:catalogue:' .. mapping_date .. ':underlyings', ARGV[index])
    end
    replies[#replies + 1] = identity or ''
    replies[#replies + 1] = last_price(ARGV[index])
    if underlying_id then
        replies[#replies + 1] = last_price(underlying_id)
    else
        replies[#replies + 1] = ''
    end
end
return replies
"""

POOL_NAMES = {
    'commodity': [
        'commodity',
    ],
    'currency': [
        'currency',
        'derivatives',
        'equity',
    ],
    'derivatives': [
        'derivatives',
        'equity',
    ],
    'equity': [
        'equity',
    ],
}


class FundsCheck:
    """Decides, for one order at a time, which brokers cannot afford it, and remembers the margin promised to the broker chosen.

    It is used by the lowest-cost selector in two steps that happen on one thread. `queue_redis_commands` adds two commands to the pipeline that already reads the instrument, so the check costs no round trip of its own: a `GET` of the unified funds document, and one Lua script that returns each leg's identity, last traded price and underlying's last traded price. `decide` then estimates the exchange margin, applies each broker's multiplier from the cost table and a cushion, and compares the result with the broker's free cash, less anything already reserved for orders just sent there. `reason` answers for a broker the placement is about to offer the order to, and `reserve_chosen` records the margin once a broker has been chosen.

    The check is off, and queues nothing, until the margin rate table has been loaded and while `UNIFIED_BROKER_INTERFACE_API_ORDER_FUNDS_CHECK` is on. When the margin cannot be worked out, for example because a market order's instrument has no quote, no broker is passed over for funds.

    Attributes:
        cost_table (BrokerCostTable): Each broker's margin multipliers and whether it gives hedge benefit.
        margin_rate_table (MarginRateTable): The exchange's margin rates.
        enabled (bool): Whether the check is switched on by configuration.
        cushion (decimal.Decimal): The share added on top of every estimate.
        default_multiplier (decimal.Decimal): The multiplier used for a broker whose surcharge has not been measured.
        maximum_age_seconds (float): How old a broker's funds may be before it is passed over.
        margin_estimate (MarginEstimate): Works out the exchange margin.
        reservations (FundsReservations): Margin promised to orders just sent.
        state (threading.local): This thread's order: `active`, `legs`, `reasons` and `requirements`.
    """

    def __init__(
        self,
        cost_table,
        margin_rate_table,
        enabled,
        cushion,
        default_multiplier,
        maximum_age_seconds,
        settle_seconds,
    ):
        """Builds the check.

        Args:
            cost_table (BrokerCostTable): Each broker's margin multipliers.
            margin_rate_table (MarginRateTable | None): The exchange's margin rates, or None to leave the check off.
            enabled (bool): Whether the check is switched on.
            cushion (float): The share added on top of every estimate, such as 0.05.
            default_multiplier (float): The multiplier for a broker whose surcharge has not been measured.
            maximum_age_seconds (float): How old a broker's funds may be.
            settle_seconds (float): How long after a reservation a funds reading is trusted to include it.

        Returns:
            None: This method returns nothing.
        """
        self.cost_table = cost_table
        self.margin_rate_table = margin_rate_table
        self.enabled = enabled
        self.cushion = decimal.Decimal(str(cushion))
        self.default_multiplier = decimal.Decimal(str(default_multiplier))
        self.maximum_age_seconds = maximum_age_seconds
        self.margin_estimate = None
        if margin_rate_table is not None:
            self.margin_estimate = MarginEstimate(margin_rate_table)
        self.reservations = FundsReservations(settle_seconds)
        self.state = threading.local()

    def is_active(self):
        """Whether the check runs for the next order.

        Returns:
            bool: True when it is switched on and the margin rate table has rows.
        """
        if not self.enabled or self.margin_rate_table is None:
            return False
        return self.margin_rate_table.is_loaded()

    def queue_redis_commands(self, pipeline, order, instrument_id, legs=None):
        """Queues the funds document and the legs' prices on the pipeline that also reads the instrument.

        Args:
            pipeline (redis.client.Pipeline): The pipeline.
            order (PlaceOrderRequest): The validated order.
            instrument_id (str): The instrument's id.
            legs (OrderLegs | None): Every leg of a strategy this order is the first of, or None for a single order.

        Returns:
            int: How many commands were queued: 2 when the check is active, else 0.
        """
        self.state.active = False
        self.state.reasons = {}
        self.state.requirements = {}
        if not self.is_active():
            return 0
        if legs is None:
            legs = OrderLegs([
                (instrument_id, order),
            ])
        self.state.active = True
        self.state.legs = legs
        pipeline.get(FUNDS_KEY)
        pipeline.eval(
            LEG_PRICES_SCRIPT,
            2,
            CURRENT_DATE_KEY,
            QUOTES_KEY,
            *legs.instrument_ids(),
        )
        return 2

    def decide(self, redis_replies, rotation, now=None):
        """Works out which brokers in the rotation cannot afford the order, and why.

        Args:
            redis_replies (list): The replies to the two commands `queue_redis_commands` queued.
            rotation (list): The broker names not excluded.
            now (datetime.datetime | None): The moment to judge the funds' age by, as naive local time, or None for now.

        Returns:
            dict: The reason (str) each broker that cannot afford the order is passed over, by broker name.
        """
        self.state.reasons = {}
        self.state.requirements = {}
        if not getattr(self.state, 'active', False) or len(redis_replies) < 2:
            return {}
        now = now or datetime.datetime.now()
        legs = self.state.legs
        priced_legs = self.priced_legs(legs, redis_replies[1])
        if priced_legs is None:
            return {}
        standalone = self.margin_estimate.required(priced_legs, False)
        hedged = standalone
        if legs.hedge_benefit:
            hedged = self.margin_estimate.required(priced_legs, True)
        funds_by_broker = self.funds_by_broker(redis_replies[0])
        pool_names = POOL_NAMES[priced_legs[0].market_category()]
        reasons = {}
        for broker_name in rotation:
            costs = self.cost_table.costs(broker_name)
            exchange_margin = standalone
            if legs.hedge_benefit and costs is not None and costs.gives_hedge_benefit:
                exchange_margin = hedged
            if exchange_margin is None:
                continue
            multiplier = self.multiplier(costs, priced_legs)
            required = exchange_margin * multiplier * (1 + self.cushion)
            required = required.quantize(PENNY, rounding=decimal.ROUND_UP)
            if required <= 0:
                continue
            self.state.requirements[broker_name] = required
            available, problem = self.available(
                broker_name,
                funds_by_broker.get(broker_name),
                pool_names,
                now,
            )
            if problem is not None:
                reasons[broker_name] = problem
            elif required > available:
                reasons[broker_name] = (
                    f'needs about {required:,.2f} of margin but has {available:,.2f} free'
                )
        self.state.reasons = reasons
        return reasons

    def reason(self, broker_name):
        """Why a broker cannot afford this thread's order, once `decide` has run.

        Args:
            broker_name (str): The broker.

        Returns:
            str | None: The reason, or None when the broker can afford it or the check did not run.
        """
        reasons = getattr(self.state, 'reasons', None) or {}
        return reasons.get(broker_name)

    def reserve_chosen(self, broker_name):
        """Reserves this thread's order's margin at the broker chosen for it, unless the order is a dry run.

        Args:
            broker_name (str): The broker chosen.

        Returns:
            None: This method returns nothing.
        """
        if not getattr(self.state, 'active', False):
            return
        for order in self.state.legs.orders():
            if getattr(order, 'dry_run', False):
                return
        requirements = getattr(self.state, 'requirements', None) or {}
        required = requirements.get(broker_name)
        if required:
            self.reservations.reserve(broker_name, required)

    def multiplier(self, costs, priced_legs):
        """The highest surcharge a broker applies to any of the legs.

        Args:
            costs (BrokerCosts | None): The broker's row, or None when the table has none.
            priced_legs (list): The `PricedLeg` legs.

        Returns:
            decimal.Decimal: The multiplier, the configured default where one is not measured.
        """
        highest = decimal.Decimal(1)
        for leg in priced_legs:
            measured = None
            if costs is not None:
                measured = costs.margin_multiplier(self.margin_estimate.margin_category(leg))
            if measured is None:
                measured = self.default_multiplier
            measured = decimal.Decimal(str(measured))
            if measured > highest:
                highest = measured
        return highest

    def available(self, broker_name, funds, pool_names, now):
        """A broker's free cash for the order's market, less what is reserved, or why it cannot be trusted.

        Args:
            broker_name (str): The broker.
            funds (dict | None): The broker's entry in the unified funds document, or None when it has none.
            pool_names (list): The money pools to look in, in order of preference.
            now (datetime.datetime): The moment to judge the funds' age by.

        Returns:
            tuple: The free cash (decimal.Decimal) and None, or zero and the reason (str) the funds cannot be used.
        """
        if funds is None:
            return decimal.Decimal(0), f'has no funds in {FUNDS_KEY}'
        if funds.get('status') != 'ok':
            return decimal.Decimal(0), f'its funds are {funds.get("status")}'
        read_at = self.read_time(funds.get('as_of'))
        if read_at is None:
            return decimal.Decimal(0), 'its funds carry no time they were read'
        age_seconds = (now - read_at).total_seconds()
        if age_seconds > self.maximum_age_seconds:
            return decimal.Decimal(0), f'its funds were read {age_seconds:.0f} seconds ago'
        free_cash = None
        pools = funds.get('pools') or {}
        for pool_name in pool_names:
            if pool_name in pools:
                free_cash = PricedLeg.decimal_or_none(pools[pool_name])
                break
        if free_cash is None:
            free_cash = PricedLeg.decimal_or_none(funds.get('available_balance'))
        if free_cash is None:
            return decimal.Decimal(0), 'its funds carry no available balance'
        return free_cash - self.reservations.reserved(broker_name, read_at), None

    def priced_legs(self, legs, script_reply):
        """Joins each leg's order with the identity and prices the Lua script returned.

        Args:
            legs (OrderLegs): The legs.
            script_reply (list): Three texts per leg: the identity JSON, the last price and the underlying's last price, each empty when not held.

        Returns:
            list | None: The `PricedLeg` legs, or None when the reply does not match or a leg's identity is missing.
        """
        if not isinstance(script_reply, list) or len(script_reply) != len(legs.legs) * 3:
            return None
        priced = []
        for position, (instrument_id, order) in enumerate(legs.legs):
            identity_text = self.text(script_reply[position * 3])
            if not identity_text:
                return None
            try:
                identity = json.loads(identity_text)
            except ValueError:
                return None
            if not isinstance(identity, dict):
                return None
            priced.append(PricedLeg(
                instrument_id,
                order,
                identity,
                PricedLeg.decimal_or_none(self.text(script_reply[position * 3 + 1])),
                PricedLeg.decimal_or_none(self.text(script_reply[position * 3 + 2])),
            ))
        return priced

    def funds_by_broker(self, funds_text):
        """Each broker's entry in the unified funds document.

        Args:
            funds_text (str | bytes | None): The document as Redis holds it.

        Returns:
            dict: Each broker's entry (dict), by broker name; empty when the document is missing or unreadable.
        """
        text = self.text(funds_text)
        if not text:
            return {}
        try:
            document = json.loads(text)
        except ValueError:
            return {}
        if not isinstance(document, dict):
            return {}
        by_broker = {}
        for entry in document.get('brokers') or []:
            if isinstance(entry, dict) and entry.get('broker'):
                by_broker[entry['broker']] = entry
        return by_broker

    @staticmethod
    def read_time(text):
        """When a broker's funds were read, from the funds document's `as_of`.

        Args:
            text (str | None): The time as `YYYY-MM-DD HH:MM:SS.ffffff` in local time.

        Returns:
            datetime.datetime | None: The time, or None when it cannot be read.
        """
        if not text:
            return None
        try:
            return datetime.datetime.strptime(text, FUNDS_TIME_FORMAT)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def text(value):
        """A Redis reply as text.

        Args:
            value (str | bytes | None): The reply.

        Returns:
            str: The text, or an empty string for None.
        """
        if value is None:
            return ''
        if isinstance(value, bytes):
            return value.decode()
        return str(value)
