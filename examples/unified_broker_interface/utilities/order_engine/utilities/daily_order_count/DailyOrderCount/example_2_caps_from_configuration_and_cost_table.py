"""Builds the daily count from configuration and the cost table, and gives back a place counted for a message that was never sent.

`from_configuration` reads `UNIFIED_BROKER_INTERFACE_API_ORDER_DAILY_CAPS`, a `broker=cap` list that `read_caps` turns into numbers, and the exit reserve. It returns None when no broker is capped and there is no cost table, so an unconfigured engine spends no Redis call on counting. When a cost table gives a broker an `orders_per_day`, that replaces the configured cap, which `cap_for` and `current_caps` show.

This program sets the caps text in the loaded configuration instead of editing `.env`, and builds a cost table in memory with one row, so nothing reads the database. It then counts one message to Dhan and pretends the message was not sent after all, for instance because the rate budget refused it; `release_if_reserved` gives the place back. A message to Fyers, which has no cap, is never counted.

A small stand-in replaces the Redis client: `register_script` returns a method that does what the reservation script does over a dictionary of strings, and `get`, `decr` and `pipeline` work on the same dictionary.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/daily_order_count/DailyOrderCount/example_2_caps_from_configuration_and_cost_table.py
"""

import decimal
import logging

from unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table import (
    BrokerCosts,
)
from unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table import (
    BrokerCostTable,
)
from unified_broker_interface.utilities.order_engine.utilities.daily_order_count import (
    DailyOrderCount,
)
from utilities.configurations import api_configuration


class CountPipeline:
    """A stand-in for a Redis pipeline that queues increments and expiries.

    Attributes:
        cache (CountRedis): The stand-in the commands run against.
        increments (list): The keys queued for an increment.
    """

    def __init__(self, cache):
        """Builds an empty pipeline.

        Args:
            cache (CountRedis): The stand-in the commands run against.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.increments = []

    def incr(self, key):
        """Queues an increment.

        Args:
            key (str): The key.

        Returns:
            CountPipeline: This pipeline.
        """
        self.increments.append(key)
        return self

    def expireat(self, key, moment):
        """Accepts an expiry, which the stand-in does not track.

        Args:
            key (str): The key.
            moment (int): The epoch at which the key expires.

        Returns:
            CountPipeline: This pipeline.
        """
        return self

    def execute(self):
        """Runs the queued increments.

        Returns:
            list: The value after each increment.
        """
        replies = []
        for key in self.increments:
            replies.append(self.cache.add(key, 1))
        self.increments = []
        return replies


class CountRedis:
    """A stand-in for the Redis client holding the daily counts as strings.

    Attributes:
        strings (dict): Each key's value, as text.
    """

    def __init__(self):
        """Builds the stand-in with no counts.

        Returns:
            None: This method returns nothing.
        """
        self.strings = {}

    def add(self, key, amount):
        """Adds to a count.

        Args:
            key (str): The key.
            amount (int): How much to add, negative to take away.

        Returns:
            int: The value afterwards.
        """
        value = int(self.strings.get(key, '0')) + amount
        self.strings[key] = str(value)
        return value

    def register_script(self, script_text):
        """Returns a callable that does what the reservation script does.

        Args:
            script_text (str): The script's Lua source, which the stand-in does not run.

        Returns:
            object: The stand-in's `run_reserve_script` method.
        """
        return self.run_reserve_script

    def run_reserve_script(self, keys, args):
        """Adds one to the count when it is below the limit.

        Args:
            keys (list): The count's key.
            args (list): The limit and the expiry epoch.

        Returns:
            int: The count after adding one, or minus one less the count when it was already at the limit.
        """
        sent = int(self.strings.get(keys[0], '0'))
        if sent >= int(args[0]):
            return -1 - sent
        return self.add(keys[0], 1)

    def get(self, key):
        """Reads a count.

        Args:
            key (str): The key.

        Returns:
            str | None: The count as text, or None when there is none.
        """
        return self.strings.get(key)

    def decr(self, key):
        """Takes one from a count.

        Args:
            key (str): The key.

        Returns:
            int: The value afterwards.
        """
        return self.add(key, -1)

    def pipeline(self, transaction=True):
        """Starts a pipeline.

        Args:
            transaction (bool): Accepted for compatibility with redis-py and ignored.

        Returns:
            CountPipeline: The pipeline.
        """
        return CountPipeline(self)


class CapsFromConfigurationExample:
    """Builds the count from configuration, with and without a cost table, and reserves and releases one place.

    Attributes:
        cache (CountRedis): The stand-in Redis client.
        logger (logging.Logger): The logger.
    """

    def __init__(self):
        """Builds the stand-in and the logger.

        Returns:
            None: This method returns nothing.
        """
        self.cache = CountRedis()
        self.logger = logging.getLogger('example')

    def cost_table(self):
        """Builds a cost table with one row, giving Zerodha a cap of 2,000 a day.

        Returns:
            BrokerCostTable: The table.
        """
        fees = {
            'delivery': decimal.Decimal('0'),
            'fno': decimal.Decimal('20'),
            'intraday': decimal.Decimal('20'),
        }
        rows = {
            'zerodha': BrokerCosts('zerodha', 10, None, None, 2000, fees),
        }
        return BrokerCostTable(self.logger, rows)

    def run(self):
        """Prints what each way of building the count gives, then the reservation and its release.

        Returns:
            None: This method returns nothing.
        """
        api_configuration['order_daily_caps'] = ''
        print(f'Nothing configured, no table: {DailyOrderCount.from_configuration(self.cache, self.logger)}')
        api_configuration['order_daily_caps'] = 'zerodha=3000, dhan=1000'
        api_configuration['order_daily_cap_exit_reserve'] = 0.05
        print(f'Caps read from text: {DailyOrderCount.read_caps(api_configuration["order_daily_caps"])}')
        daily_count = DailyOrderCount.from_configuration(self.cache, self.logger, self.cost_table())
        print(f'Configured caps: {daily_count.caps}')
        print(f'Caps in force: {daily_count.current_caps()}')
        print(f'Zerodha cap: {daily_count.cap_for("zerodha")}, dhan cap: {daily_count.cap_for("dhan")}, fyers cap: {daily_count.cap_for("fyers")}')
        daily_count.refuse_if_capped('dhan', False)
        print(f'Dhan after reserving a place: {daily_count.sent_today("dhan")}')
        daily_count.release_if_reserved()
        print(f'Dhan after the message was not sent: {daily_count.sent_today("dhan")}')
        daily_count.refuse_if_capped('fyers', False)
        daily_count.count_sent('fyers')
        print(f'Keys in Redis after a message to fyers, which has no cap: {sorted(self.cache.strings)}')
        try:
            DailyOrderCount.read_caps('zerodha:3000')
        except ValueError as error:
            print(f'Bad caps text refused: {error}')
        print(f'Counts: {daily_count.counts()}')


if __name__ == '__main__':
    CapsFromConfigurationExample().run()
