"""Each order goes to the broker that charges least for it while that broker still has room in its order-rate budgets."""

import collections
import datetime
import threading
import time

from unified_broker_interface.utilities.broker_selection.base import (
    BrokerSelector,
)
from unified_broker_interface.utilities.broker_selection.utilities.funds_check import (
    FundsCheck,
)
from unified_broker_interface.utilities.exchange_calendar import (
    TRADING_HOURS,
)
from unified_broker_interface.utilities.order_engine.utilities.daily_order_count import (
    COUNT_KEY_PREFIX,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    INDIA,
)
from unified_broker_interface.utilities.order_engine.utilities.rate_budget import (
    HOUR_KEY_SUFFIX,
    HOUR_SECONDS,
    MICROSECONDS_PER_SECOND,
    MINUTE_KEY_SUFFIX,
    MINUTE_SECONDS,
    RATE_KEY_PREFIX,
)
from utilities.configurations import api_configuration

COUNTS_SCRIPT = """
local now_parts = redis.call('TIME')
local now = tonumber(now_parts[1]) * 1000000 + tonumber(now_parts[2])
local counts = {}
for index = 1, #KEYS, 4 do
    counts[#counts + 1] = redis.call('ZCOUNT', KEYS[index], '(' .. (now - tonumber(ARGV[1])), '+inf')
    counts[#counts + 1] = redis.call('ZCOUNT', KEYS[index + 1], '(' .. (now - tonumber(ARGV[2])), '+inf')
    counts[#counts + 1] = redis.call('ZCOUNT', KEYS[index + 2], '(' .. (now - tonumber(ARGV[3])), '+inf')
    counts[#counts + 1] = tonumber(redis.call('GET', KEYS[index + 3]) or '0')
end
return counts
"""


class LowestCostSelector(BrokerSelector):
    """Offers each order first to the broker that charges least for its kind of order, keeping every broker inside its order-rate budgets.

    Every number it uses comes from the broker cost table, `unified.broker_order_costs`; no broker, fee or limit is written here. The brokers are sorted on five things, each one only breaking the ties the one before leaves:

    1. Whether any per-minute, per-hour or per-day budget is already used up. Such a broker is still listed, but last.
    2. The brokerage for the order's category: `fno` for a future or option, `delivery` for a `CNC` order, and `intraday` for anything else.
    3. How much the broker saves on the other two categories, compared with the dearest broker in the rotation. A broker that is cheap only for this category is used before one that other kinds of order need, so an equity delivery order does not use up the room at a broker that is free for futures and options too.
    4. Pressure: the fullest of the broker's windows, as a share of what the window allows. A per-day budget is paced: by a given time of the NSE equity session it allows its share of the day so far plus a tenth, so a broker's day is not spent in the first hour. Lower pressure goes first, which shares orders between equally cheap brokers in proportion to their limits.
    5. The broker's place in the rotation, so the order is always the same for the same counts.

    Before any of that, a broker that cannot afford the order is passed over altogether, when the margin rate table is loaded. `FundsCheck` estimates the margin the order, or the whole strategy it starts, needs at each broker, from the exchange's rates and the broker's measured surcharge, and compares it with the broker's free cash in `unified:portfolio:funds`. The placement asks `passed_over_reason` for each broker it is about to offer the order to, so a broker that cannot afford it is skipped with its reason. The check's two commands ride on the same pipeline as the counts.

    The counts are read in one Redis command on the pipeline that also reads the instrument: a Lua script returns every broker's messages in the last second, minute and hour from the rate budget's windows, and today's count from the daily order count. Those windows fill only when a message is sent, but the order engine chooses a broker when an order arrives and sends it a moment later from the broker's lane, so a burst of orders would all see the same counts and all go to one broker. The selector therefore also remembers, in memory, the brokers it has chosen in the last second, minute and hour, and uses the higher of the two counts.

    Attributes:
        PACING_SLACK (float): The share of a per-day budget allowed on top of the paced share.
        second_window_seconds (float): The length of the rate budget's per-second window.
        exit_reserve (float): The share of a per-day budget kept for closing positions, which new orders cannot use.
        session_opens (datetime.time): When the NSE equity session opens, which the per-day pacing starts from.
        session_closes (datetime.time): When it closes, by which time the whole per-day budget is allowed.
        queued (threading.local): The table rows and broker names this thread queued counts for, in `rows` and `names`.
        chosen (dict): For each broker, three `collections.deque` of the monotonic times it was chosen, by window: `second`, `minute` and `hour`.
        chosen_lock (threading.Lock): Guards `chosen`, which several threads update.
        funds_check (FundsCheck): Decides which brokers cannot afford an order, and reserves the margin of the one chosen.
    """

    NAME = 'lowest_cost'
    PACING_SLACK = 0.1

    def __init__(self, cost_table, margin_rate_table=None):
        """Builds the selector.

        Args:
            cost_table (BrokerCostTable): Each broker's brokerage, order-rate limits and margin multipliers.
            margin_rate_table (MarginRateTable | None): The exchange's margin rates, or None to leave the funds check off.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(cost_table, margin_rate_table)
        self.second_window_seconds = api_configuration['order_rate_window_seconds']
        self.exit_reserve = api_configuration['order_daily_cap_exit_reserve']
        equity_session = TRADING_HOURS['nse']['equity']['sessions'][0]
        self.session_opens = datetime.time.fromisoformat(equity_session['opens'])
        self.session_closes = datetime.time.fromisoformat(equity_session['closes'])
        self.queued = threading.local()
        self.chosen = {}
        self.chosen_lock = threading.Lock()
        self.funds_check = FundsCheck(
            cost_table,
            margin_rate_table,
            api_configuration['order_funds_check'],
            api_configuration['order_margin_cushion'],
            api_configuration['order_margin_default_multiplier'],
            api_configuration['order_funds_maximum_age_seconds'],
            api_configuration['order_funds_settle_seconds'],
        )

    def queue_redis_commands(self, pipeline, order, instrument_id, legs=None):
        """Queues the script that reads every broker's counts, then the funds check's commands.

        Args:
            pipeline (redis.client.Pipeline): The pipeline to queue the commands on.
            order (PlaceOrderRequest): The validated order.
            instrument_id (str): The instrument's id.
            legs (OrderLegs | None): Every leg of a strategy this order is the first of, or None for a single order.

        Returns:
            int: 1 for the counts script, plus 2 when the funds check is active.
        """
        rows = self.cost_table.rows
        names = sorted(rows)
        self.queued.rows = rows
        self.queued.names = names
        keys = []
        for broker_name in names:
            keys.append(RATE_KEY_PREFIX + broker_name)
            keys.append(RATE_KEY_PREFIX + broker_name + MINUTE_KEY_SUFFIX)
            keys.append(RATE_KEY_PREFIX + broker_name + HOUR_KEY_SUFFIX)
            keys.append(COUNT_KEY_PREFIX + broker_name)
        pipeline.eval(
            COUNTS_SCRIPT,
            len(keys),
            *keys,
            int(self.second_window_seconds * MICROSECONDS_PER_SECOND),
            MINUTE_SECONDS * MICROSECONDS_PER_SECOND,
            HOUR_SECONDS * MICROSECONDS_PER_SECOND,
        )
        funds_command_count = self.funds_check.queue_redis_commands(
            pipeline,
            order,
            instrument_id,
            legs,
        )
        return 1 + funds_command_count

    def ranked_brokers(self, order, instrument, rotation, redis_replies):
        """Sorts the rotation by blocked, fee, versatility, pressure and place, and decides which brokers cannot afford the order.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument (Instrument): The tradeable instrument.
            rotation (list): The broker names not excluded, in turn order.
            redis_replies (list): The counts script's reply first, then the funds check's two replies when it is active.

        Returns:
            list: The broker names in the order to offer them the order.
        """
        self.funds_check.decide(redis_replies[1:], rotation)
        rows = getattr(self.queued, 'rows', None)
        names = getattr(self.queued, 'names', None)
        if rows is None or names is None:
            rows = self.cost_table.rows
            names = []
        stored_counts = self.stored_counts(names, redis_replies)
        category = self.category(order, instrument)
        highest_fees = self.highest_fees(rotation, rows)
        day_fraction = self.day_fraction()
        sort_keys = []
        for position, broker_name in enumerate(rotation):
            costs = rows.get(broker_name)
            if costs is None:
                sort_keys.append((
                    (1, 0, 0, 0, 0, position),
                    broker_name,
                ))
                continue
            used = self.used_counts(broker_name, stored_counts)
            blocked = 0
            if self.is_blocked(costs, used):
                blocked = 1
            sort_keys.append((
                (
                    0,
                    blocked,
                    costs.fee(category),
                    self.versatility(costs, category, highest_fees),
                    self.pressure(costs, used, day_fraction),
                    position,
                ),
                broker_name,
            ))
        sort_keys.sort()
        ranked = []
        for sort_key, broker_name in sort_keys:
            ranked.append(broker_name)
        return ranked

    def passed_over_reason(self, broker_name):
        """Why a broker cannot afford the order this thread last ranked, or None.

        Args:
            broker_name (str): The broker.

        Returns:
            str | None: The reason, such as `needs about 185,671.65 of margin but has 12,675.96 free`, or None.
        """
        return self.funds_check.reason(broker_name)

    def record_chosen(self, broker_name):
        """Remembers that a broker was chosen now, until its counts in Redis catch up, and reserves the order's margin there.

        Args:
            broker_name (str): The broker chosen.

        Returns:
            None: This method returns nothing.
        """
        self.funds_check.reserve_chosen(broker_name)
        now = time.monotonic()
        with self.chosen_lock:
            windows = self.chosen.get(broker_name)
            if windows is None:
                windows = {
                    'second': collections.deque(),
                    'minute': collections.deque(),
                    'hour': collections.deque(),
                }
                self.chosen[broker_name] = windows
            windows['second'].append(now)
            windows['minute'].append(now)
            windows['hour'].append(now)

    def chosen_counts(self, broker_name):
        """How often this process chose a broker in the last second, minute and hour.

        Args:
            broker_name (str): The broker.

        Returns:
            dict: The counts (int) by window: `second`, `minute` and `hour`.
        """
        now = time.monotonic()
        window_lengths = {
            'second': self.second_window_seconds,
            'minute': MINUTE_SECONDS,
            'hour': HOUR_SECONDS,
        }
        counts = {
            'second': 0,
            'minute': 0,
            'hour': 0,
        }
        with self.chosen_lock:
            windows = self.chosen.get(broker_name)
            if windows is None:
                return counts
            for window_name, moments in windows.items():
                oldest_kept = now - window_lengths[window_name]
                while moments and moments[0] <= oldest_kept:
                    moments.popleft()
                counts[window_name] = len(moments)
        return counts

    def stored_counts(self, names, redis_replies):
        """Reads the counts script's reply into each broker's counts.

        Args:
            names (list): The broker names the script was queued for, in order.
            redis_replies (list): The selector's replies, whose first is the script's.

        Returns:
            dict: For each broker, a dict of counts (int) by window: `second`, `minute`, `hour` and `day`. A broker the reply does not cover is left out.
        """
        stored = {}
        if not redis_replies:
            return stored
        reply = redis_replies[0]
        if not isinstance(reply, list) or len(reply) != len(names) * 4:
            return stored
        for index, broker_name in enumerate(names):
            stored[broker_name] = {
                'second': int(reply[index * 4]),
                'minute': int(reply[index * 4 + 1]),
                'hour': int(reply[index * 4 + 2]),
                'day': int(reply[index * 4 + 3]),
            }
        return stored

    def used_counts(self, broker_name, stored_counts):
        """A broker's messages in each window: the higher of Redis's count and this process's own choices.

        Args:
            broker_name (str): The broker.
            stored_counts (dict): Each broker's counts from Redis.

        Returns:
            dict: The counts (int) by window: `second`, `minute`, `hour` and `day`.
        """
        used = {
            'second': 0,
            'minute': 0,
            'hour': 0,
            'day': 0,
        }
        stored = stored_counts.get(broker_name)
        if stored is not None:
            used.update(stored)
        chosen = self.chosen_counts(broker_name)
        for window_name, count in chosen.items():
            if count > used[window_name]:
                used[window_name] = count
        return used

    def category(self, order, instrument):
        """Which of the table's three prices applies to the order.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument (Instrument): The tradeable instrument.

        Returns:
            str: `fno` for a future or option, `delivery` for a `CNC` order, and `intraday` otherwise.
        """
        if instrument.kind() == 'derivative':
            return 'fno'
        if order.product == 'CNC':
            return 'delivery'
        return 'intraday'

    def highest_fees(self, rotation, rows):
        """The dearest brokerage in each category among the brokers in the rotation that have a row.

        Args:
            rotation (list): The broker names not excluded.
            rows (dict): The cost table's rows by broker name.

        Returns:
            dict: The highest brokerage (decimal.Decimal or int) by category.
        """
        highest = {}
        for category in self.cost_table.CATEGORIES:
            highest[category] = 0
        for broker_name in rotation:
            costs = rows.get(broker_name)
            if costs is None:
                continue
            for category in self.cost_table.CATEGORIES:
                if costs.fee(category) > highest[category]:
                    highest[category] = costs.fee(category)
        return highest

    def versatility(self, costs, category, highest_fees):
        """How much a broker saves on the categories other than this order's, against the dearest broker.

        Args:
            costs (BrokerCosts): The broker's row.
            category (str): The order's category.
            highest_fees (dict): The highest brokerage by category.

        Returns:
            decimal.Decimal | int: The saving summed over the other categories.
        """
        saving = 0
        for other_category in self.cost_table.CATEGORIES:
            if other_category == category:
                continue
            saving = saving + highest_fees[other_category] - costs.fee(other_category)
        return saving

    def is_blocked(self, costs, used):
        """Whether any per-minute, per-hour or per-day budget has no room for a new order.

        The per-second budget is left out, because a full second empties within the rate budget's short wait.

        Args:
            costs (BrokerCosts): The broker's row.
            used (dict): The broker's counts by window.

        Returns:
            bool: True when a budget is used up.
        """
        if costs.orders_per_minute is not None and used['minute'] >= costs.orders_per_minute:
            return True
        if costs.orders_per_hour is not None and used['hour'] >= costs.orders_per_hour:
            return True
        if costs.orders_per_day is not None:
            entry_limit = costs.orders_per_day - int(costs.orders_per_day * self.exit_reserve)
            if used['day'] >= entry_limit:
                return True
        return False

    def pressure(self, costs, used, day_fraction):
        """The fullest of the broker's windows, as a share of what each allows now.

        Args:
            costs (BrokerCosts): The broker's row.
            used (dict): The broker's counts by window.
            day_fraction (float): How much of the equity session has passed, from 0 to 1.

        Returns:
            float: The highest share, 0 when the broker has no limits.
        """
        shares = [
            0.0,
        ]
        if costs.orders_per_second is not None:
            shares.append(used['second'] / costs.orders_per_second)
        if costs.orders_per_minute is not None:
            shares.append(used['minute'] / costs.orders_per_minute)
        if costs.orders_per_hour is not None:
            shares.append(used['hour'] / costs.orders_per_hour)
        if costs.orders_per_day is not None:
            paced_allowance = costs.orders_per_day * (day_fraction + self.PACING_SLACK)
            allowance = min(costs.orders_per_day, paced_allowance)
            shares.append(used['day'] / allowance)
        return max(shares)

    def day_fraction(self, now=None):
        """How much of today's NSE equity session has passed.

        Args:
            now (datetime.datetime | None): The moment to reckon from, or None for now in IST.

        Returns:
            float: 0 before the session opens, 1 after it closes, and the share passed in between.
        """
        now = now or datetime.datetime.now(INDIA)
        opens = now.replace(
            hour=self.session_opens.hour,
            minute=self.session_opens.minute,
            second=0,
            microsecond=0,
        )
        closes = now.replace(
            hour=self.session_closes.hour,
            minute=self.session_closes.minute,
            second=0,
            microsecond=0,
        )
        if now <= opens:
            return 0.0
        if now >= closes:
            return 1.0
        return (now - opens).total_seconds() / (closes - opens).total_seconds()
