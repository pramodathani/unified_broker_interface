"""Answers one request for daily candles from the database and stores the copy, then answers a narrower request from that copy alone.

`/api/instruments/prices` builds one `PriceCache` per request for the series it serves: one instrument, one interval, one price basis and one `known_as_of`. `load` reads the stored copy in one Redis round trip. When the copy `covers` the range asked for, the route slices it with `between` and sends no database query. Otherwise it reads the database over `query_range` and hands the rows to `replace`, which holds them and stores them for the next request.

This program plays the route twice. A small stand-in Redis keeps strings in a dictionary and records every command, and a stand-in price table makes up one candle per weekday of September 2026, so the program reads no real database. The first request asks for 1 to 10 September, finds no copy, reads the stand-in table and stores what it read. The second asks for 3 to 5 September and is answered from the copy.

Notice that the first request queries the table once and sends one SET, that the second loads the copy, covers the range, returns two candles, because 5 September is a Saturday, and queries nothing, and that the key names the instrument, the interval, the basis and `latest`.

Run it from the project root:

    python examples/unified_broker_interface/utilities/price_cache/PriceCache/example_1_second_request_skips_the_database.py
"""

import datetime

from unified_broker_interface.utilities.instrument_identity import (
    INDIA,
)
from unified_broker_interface.utilities.price_cache import (
    PriceCache,
)

INSTRUMENT_ID = '22222222-2222-5222-8222-000000000001'
COLUMNS = [
    'time',
    'open',
    'high',
    'low',
    'close',
    'volume',
]


class StringRedis:
    """A stand-in for the Redis client that keeps strings in a dictionary and records each command.

    Attributes:
        strings (dict): The value of each key.
        commands (list): The name and key of every command run.
    """

    def __init__(self):
        """Builds the stand-in with no keys.

        Returns:
            None: This method returns nothing.
        """
        self.strings = {}
        self.commands = []

    def pipeline(self):
        """Starts a pipeline.

        Returns:
            StringPipeline: The pipeline.
        """
        return StringPipeline(self)

    def set(self, key, value, ex=None):
        """Stores a string.

        Args:
            key (str): The key.
            value (str): The value.
            ex (int | None): The expiry in seconds, which the stand-in records but does not apply.

        Returns:
            bool: True.
        """
        self.commands.append(f'SET {key} EX {ex}')
        self.strings[key] = value
        return True


class StringPipeline:
    """A stand-in pipeline that queues GET commands and runs them together.

    Attributes:
        client (StringRedis): The stand-in the commands run against.
        keys (list): The keys queued for a GET.
    """

    def __init__(self, client):
        """Builds an empty pipeline.

        Args:
            client (StringRedis): The stand-in the commands run against.

        Returns:
            None: This method returns nothing.
        """
        self.client = client
        self.keys = []

    def get(self, key):
        """Queues a GET.

        Args:
            key (str): The key.

        Returns:
            StringPipeline: This pipeline.
        """
        self.keys.append(key)
        return self

    def execute(self):
        """Runs every queued GET.

        Returns:
            list: One value or None per key, in order.
        """
        values = []
        for key in self.keys:
            self.client.commands.append(f'GET {key}')
            values.append(self.client.strings.get(key))
        return values


class StandInPriceTable:
    """A stand-in for the price history table that makes up one daily candle per weekday.

    Attributes:
        queries (int): How many times the table was read.
    """

    def __init__(self):
        """Builds the table.

        Returns:
            None: This method returns nothing.
        """
        self.queries = 0

    def read(self, from_date, to_date):
        """Reads the candles of every weekday in a range.

        Args:
            from_date (datetime.date): The first day, inclusive.
            to_date (datetime.date): The last day, inclusive.

        Returns:
            list: The candles, oldest first, each as time, open, high, low, close and volume.
        """
        self.queries += 1
        candles = []
        day = from_date
        while day <= to_date:
            if day.weekday() < 5:
                moment = datetime.datetime.combine(day, datetime.time(), tzinfo=INDIA)
                close = 1500.0 + day.day
                candles.append([
                    moment.isoformat(),
                    close - 5,
                    close + 10,
                    close - 12,
                    close,
                    100000 + day.day,
                ])
            day = day + datetime.timedelta(days=1)
        return candles


class SecondRequestSkipsTheDatabaseExample:
    """Serves two requests for one series, the second from the stored copy.

    Attributes:
        client (StringRedis): The stand-in Redis.
        table (StandInPriceTable): The stand-in price table.
    """

    def __init__(self):
        """Builds the stand-ins.

        Returns:
            None: This method returns nothing.
        """
        self.client = StringRedis()
        self.table = StandInPriceTable()

    def serve(self, from_date, to_date):
        """Serves one request the way the prices route does.

        Args:
            from_date (datetime.date): The first day asked for.
            to_date (datetime.date): The last day asked for.

        Returns:
            None: This method returns nothing.
        """
        print(f'Request for {from_date} to {to_date}:')
        price_cache = PriceCache(self.client, INSTRUMENT_ID, 'day', 'adjusted', None, COLUMNS)
        price_cache.load()
        print(f'  loaded a copy: {price_cache.loaded}, covering {price_cache.from_date} to {price_cache.to_date}')
        if not price_cache.covers(from_date, to_date):
            query_from, query_to = price_cache.query_range(from_date, to_date, 2000)
            candles = self.table.read(query_from, query_to)
            price_cache.replace(query_from, query_to, candles)
            print(f'  read {len(candles)} candles for {query_from} to {query_to} and stored them')
        start = datetime.datetime.combine(from_date, datetime.time(), tzinfo=INDIA)
        end = datetime.datetime.combine(to_date + datetime.timedelta(days=1), datetime.time(), tzinfo=INDIA)
        served = price_cache.between(start, end)
        for candle in served:
            print(f'  {candle[0][:10]} close {candle[4]}')

    def run(self):
        """Serves the two requests and prints the Redis commands and database reads.

        Returns:
            None: This method returns nothing.
        """
        self.serve(datetime.date(2026, 9, 1), datetime.date(2026, 9, 10))
        self.serve(datetime.date(2026, 9, 3), datetime.date(2026, 9, 5))
        print(f'Database reads: {self.table.queries}')
        print('Redis commands:')
        for command in self.client.commands:
            print(f'  {command}')


if __name__ == '__main__':
    SecondRequestSkipsTheDatabaseExample().run()
