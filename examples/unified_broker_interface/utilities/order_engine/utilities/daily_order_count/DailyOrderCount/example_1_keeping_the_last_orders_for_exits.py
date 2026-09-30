"""Counts a day's order messages to a capped broker and shows new entries stopping before the cap so exits can still be sent.

Some brokers refuse every order message past a fixed number a day, including the order that would close a position. `DailyOrderCount` therefore stops new entries a little early and keeps the rest of the cap for exits. Before each message, `refuse_if_capped` checks and counts it in one Redis step, raising `RefusedRequestError` with HTTP 429 when there is no room; once the message is sent, `count_sent` sees that it was already counted and does not count it again.

This program gives Zerodha a cap of ten messages with a fifth kept back for exits, so `entry_limit` is eight. It sends eight entries, has a ninth refused, sends two exits using the reserve, and has a third exit refused at the full cap. It also prints the Redis key the count lives in and `next_reset`, the 06:00 IST expiry, for a fixed moment on 30 September 2026.

The real count runs a small Lua script in Redis. A small stand-in replaces the Redis client: `register_script` returns a method that does what that script does over a dictionary of strings, and `get`, `decr` and `pipeline` work on the same dictionary.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/daily_order_count/DailyOrderCount/example_1_keeping_the_last_orders_for_exits.py
"""

import datetime
import logging
import zoneinfo

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.daily_order_count import (
    DailyOrderCount,
)


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


class KeepingTheLastOrdersForExitsExample:
    """Sends entries and exits to a broker capped at ten a day.

    Attributes:
        daily_count (DailyOrderCount): The count being shown.
        orders (list): The messages to send, True for an exit and False for an entry.
    """

    def __init__(self):
        """Builds the count with Zerodha capped at ten and a fifth kept for exits.

        Returns:
            None: This method returns nothing.
        """
        caps = {
            'zerodha': 10,
        }
        self.daily_count = DailyOrderCount(CountRedis(), caps, 0.2, logging.getLogger('example'))
        self.orders = []
        for _ in range(9):
            self.orders.append(False)
        for _ in range(3):
            self.orders.append(True)

    def run(self):
        """Prints the limits, then the answer for each message and the count after it.

        Returns:
            None: This method returns nothing.
        """
        moment = datetime.datetime(2026, 9, 30, 14, 5, tzinfo=zoneinfo.ZoneInfo('Asia/Kolkata'))
        reset = datetime.datetime.fromtimestamp(self.daily_count.next_reset(moment), zoneinfo.ZoneInfo('Asia/Kolkata'))
        print(f'Count key: {self.daily_count.key("zerodha")}')
        print(f'Counts expire at: {reset.isoformat()}')
        print(f'Cap: {self.daily_count.cap_for("zerodha")}, entries stop at: {self.daily_count.entry_limit(10)}')
        for number, closes_position in enumerate(self.orders, start=1):
            kind = 'exit' if closes_position else 'entry'
            try:
                self.daily_count.refuse_if_capped('zerodha', closes_position)
            except RefusedRequestError as refusal:
                print(f'Message {number} ({kind}): refused with {refusal.status}: {refusal.body["error"]}')
                continue
            self.daily_count.count_sent('zerodha')
            print(f'Message {number} ({kind}): sent, count now {self.daily_count.sent_today("zerodha")}')
        print(f'Counts: {self.daily_count.counts()}')


if __name__ == '__main__':
    KeepingTheLastOrdersForExitsExample().run()
