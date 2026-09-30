"""Shows the three reasons a stored candle copy is not used as it stands: the loader ran again, the columns changed, or the request reaches outside it.

A copy records the `finished` time of the price history run that was in force when it was built, read from `unified:prices:last_run`. When the loader has run since, `load` ignores the copy, because adjusted prices may have changed. It also ignores a copy whose columns differ from the answer's. A current copy that does not cover the request makes `query_range` widen the database read to the union of the two ranges, unless the union would span more days than the interval allows, and a Redis that cannot be reached is logged and treated as holding nothing.

This program stores one copy for 10 to 20 August 2026 in a stand-in Redis, stamped with a loader run, and then builds a `PriceCache` for five situations. The stand-in keeps strings in a dictionary; a second stand-in fails every command, as an unreachable Redis does. A logging handler prints the cache's warning to the output without a timestamp. No database is read, because the program only asks which range would be read.

Notice that the copy is loaded only while the stamp and the columns match; that a request for 15 to 25 August reads 10 to 25 August, so the copy stored afterwards is one growing entry, but a request for 1 to 30 September stays as asked when the limit is 30 days; and that the unreachable Redis is logged and nothing is loaded.

Run it from the project root:

    python examples/unified_broker_interface/utilities/price_cache/PriceCache/example_2_stale_copies_and_wider_ranges.py
"""

import datetime
import json
import logging
import sys

from unified_broker_interface.utilities.price_cache import (
    PriceCache,
)

INSTRUMENT_ID = '22222222-2222-5222-8222-000000000002'
KEY = f'unified:prices:cache:{INSTRUMENT_ID}:day:adjusted:latest'
COLUMNS = [
    'time',
    'close',
]
FIRST_RUN = '2026-08-20T19:05:00+05:30'
SECOND_RUN = '2026-08-21T19:05:00+05:30'


class StringRedis:
    """A stand-in for the Redis client that keeps strings in a dictionary.

    Attributes:
        strings (dict): The value of each key.
    """

    def __init__(self):
        """Builds the stand-in with no keys.

        Returns:
            None: This method returns nothing.
        """
        self.strings = {}

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
            ex (int | None): The expiry in seconds, which the stand-in ignores.

        Returns:
            bool: True.
        """
        del ex
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
            values.append(self.client.strings.get(key))
        return values


class UnreachableRedis:
    """A stand-in for a Redis client that cannot reach its server."""

    def pipeline(self):
        """Fails as a client with no server does.

        Returns:
            None: This method never returns.

        Raises:
            ConnectionError: Always.
        """
        raise ConnectionError('Error 111 connecting to 127.0.0.1:6379. Connection refused.')


class StaleCopiesAndWiderRangesExample:
    """Loads one stored copy under five different conditions.

    Attributes:
        client (StringRedis): The stand-in Redis holding the copy.
    """

    def __init__(self):
        """Stores a copy of 10 to 20 August, stamped with the first loader run.

        Returns:
            None: This method returns nothing.
        """
        self.client = StringRedis()
        self.set_last_run(FIRST_RUN)
        candles = [
            [
                '2026-08-10T00:00:00+05:30',
                2874.05,
            ],
            [
                '2026-08-20T00:00:00+05:30',
                2890.5,
            ],
        ]
        builder = PriceCache(self.client, INSTRUMENT_ID, 'day', 'adjusted', None, COLUMNS)
        builder.load()
        builder.replace(datetime.date(2026, 8, 10), datetime.date(2026, 8, 20), candles)

    def set_last_run(self, finished):
        """Records a price history run in the stand-in Redis.

        Args:
            finished (str): When the run finished.

        Returns:
            None: This method returns nothing.
        """
        last_run = {
            'finished': finished,
        }
        self.client.strings['unified:prices:last_run'] = json.dumps(last_run)

    def loaded(self, label, client, columns):
        """Builds a cache for the series, loads it and prints whether the copy was used.

        Args:
            label (str): What is being tried, for the printout.
            client (StringRedis | UnreachableRedis): The Redis client.
            columns (list): The columns the answer carries.

        Returns:
            PriceCache: The loaded cache.
        """
        price_cache = PriceCache(client, INSTRUMENT_ID, 'day', 'adjusted', None, columns)
        price_cache.load()
        print(f'{label}: loaded {price_cache.loaded}, holding {len(price_cache.candles)} candles')
        return price_cache

    def run(self):
        """Tries the copy under each condition and prints what the cache decides.

        Returns:
            None: This method returns nothing.
        """
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('  log %(levelname)s: %(message)s'))
        logging.getLogger('rest_api.prices').addHandler(handler)
        print(f'Stored copy under {KEY}')
        current = self.loaded('Same loader run', self.client, COLUMNS)
        request_from = datetime.date(2026, 8, 15)
        request_to = datetime.date(2026, 8, 25)
        print(f'  covers 15 to 25 August: {current.covers(request_from, request_to)}')
        print(f'  read instead: {current.query_range(request_from, request_to, 2000)}')
        september = current.query_range(datetime.date(2026, 9, 1), datetime.date(2026, 9, 30), 30)
        print(f'  1 to 30 September with a 30 day limit reads: {september}')
        wider_columns = [
            'time',
            'close',
            'volume',
        ]
        self.loaded('Different columns', self.client, wider_columns)
        self.set_last_run(SECOND_RUN)
        stale = self.loaded('Loader ran again', self.client, COLUMNS)
        print(f'  covers 10 to 20 August: {stale.covers(datetime.date(2026, 8, 10), datetime.date(2026, 8, 20))}')
        self.loaded('Redis unreachable', UnreachableRedis(), COLUMNS)


if __name__ == '__main__':
    StaleCopiesAndWiderRangesExample().run()
