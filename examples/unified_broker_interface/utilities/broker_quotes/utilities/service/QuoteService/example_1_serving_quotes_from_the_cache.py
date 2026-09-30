"""Serves two instruments' quotes from the Redis quote cache in one round trip, without asking any broker.

`QuoteService` answers the REST API's `/ltp`, `/ohlc` and `/quote` routes. For each instrument it reads two Redis hashes in one pipeline: `unified:quotes:live`, which the unified market feed keeps, and `unified:quotes:fetched`, which holds quotes it fetched from brokers earlier. It takes the more recently received of the two, and when that quote is not marked stale and was received in the last five minutes it is served as it is, with `source` set to `cache`. Only instruments without such a quote are asked of a broker.

The Redis client is a small stand-in class holding one live quote for INFY, one older fetched quote for INFY, and one fetched quote for RELIANCE; it counts round trips. The worker's mapping cache is a stand-in too, which records whether any broker handle was looked up. The quotes are stamped a minute or two before the moment the program runs, so they are always fresh; the program prints prices and sources rather than times, so its output is the same on every run.

In the output, notice that INFY's live quote wins over its older fetched one, that both instruments needed only one Redis round trip, and that no broker handle was looked up.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/utilities/service/QuoteService/example_1_serving_quotes_from_the_cache.py
"""

import datetime
import json
import time

from unified_broker_interface.utilities.broker_quotes.utilities.service import (
    QuoteService,
)

INFY = '22222222-2222-5222-8222-000000000001'
RELIANCE = '22222222-2222-5222-8222-000000000002'


class QuoteCachePipeline:
    """A stand-in for a Redis pipeline that queues hash reads and answers them together.

    Attributes:
        redis (QuoteCacheRedis): The stand-in Redis client the pipeline belongs to.
        commands (list): The (key, field) pairs queued.
    """

    def __init__(self, redis):
        """Starts an empty pipeline.

        Args:
            redis (QuoteCacheRedis): The stand-in Redis client.

        Returns:
            None: This method returns nothing.
        """
        self.redis = redis
        self.commands = []

    def hget(self, key, field):
        """Queues a hash field read.

        Args:
            key (str): The hash key.
            field (str): The field.

        Returns:
            QuoteCachePipeline: This pipeline.
        """
        self.commands.append((key, field))
        return self

    def execute(self):
        """Answers every queued read in one round trip.

        Returns:
            list: The stored value of each field, or None where it is absent.
        """
        self.redis.round_trips += 1
        replies = []
        for key, field in self.commands:
            replies.append(self.redis.hashes.get(key, {}).get(field))
        return replies


class QuoteCacheRedis:
    """A stand-in for the Redis client holding the two quote hashes.

    Attributes:
        hashes (dict): Hash keys to their fields and stored JSON values.
        round_trips (int): How many pipelines were executed.
    """

    def __init__(self, hashes):
        """Holds the given hashes.

        Args:
            hashes (dict): Hash keys to their fields and stored JSON values.

        Returns:
            None: This method returns nothing.
        """
        self.hashes = hashes
        self.round_trips = 0

    def pipeline(self):
        """Starts a pipeline.

        Returns:
            QuoteCachePipeline: The pipeline.
        """
        return QuoteCachePipeline(self)


class RecordingMappingCache:
    """A stand-in for the worker's mapping cache that records every broker handle lookup.

    Attributes:
        lookups (list): The instrument ids asked about.
    """

    def __init__(self):
        """Builds the stand-in with no lookups made.

        Returns:
            None: This method returns nothing.
        """
        self.lookups = []

    def order_handles_for_instruments(self, instrument_identifiers, as_of_date, brokers=None):
        """Records a lookup and finds no broker handles.

        Args:
            instrument_identifiers (list): The instrument ids asked about.
            as_of_date (datetime.date): The mapping date.
            brokers (list | None): The brokers to restrict the answer to.

        Returns:
            dict: Always empty.
        """
        self.lookups.extend(instrument_identifiers)
        return {}


class ServingQuotesFromTheCacheExample:
    """Asks the quote service for two cached instruments, and then for one of them alone.

    Attributes:
        cache (QuoteCacheRedis): The stand-in Redis client.
        mapping_cache (RecordingMappingCache): The stand-in mapping cache.
        service (QuoteService): The quote service being shown.
    """

    def __init__(self):
        """Fills the stand-in cache with quotes received shortly before now and builds the service.

        Returns:
            None: This method returns nothing.
        """
        now = time.time()
        live_quotes = {
            INFY: self.stored_quote(INFY, 1512.35, now - 60),
        }
        fetched_quotes = {
            INFY: self.stored_quote(INFY, 1509.9, now - 240),
            RELIANCE: self.stored_quote(RELIANCE, 1381.2, now - 90),
        }
        self.cache = QuoteCacheRedis({
            'unified:quotes:live': live_quotes,
            'unified:quotes:fetched': fetched_quotes,
        })
        self.mapping_cache = RecordingMappingCache()
        self.service = QuoteService(self.mapping_cache, self.cache)

    def stored_quote(self, instrument_id, last_price, received_at):
        """A unified quote document as the cache stores it.

        Args:
            instrument_id (str): The instrument id.
            last_price (float): The last price.
            received_at (float): When the quote was received, in epoch seconds.

        Returns:
            str: The document as JSON.
        """
        document = {
            'instrument_id': instrument_id,
            'exchange': 'nse',
            'segment': 'nse_equities',
            'last_price': last_price,
            'received_at': received_at,
            'stale': False,
        }
        return json.dumps(document)

    def run(self):
        """Prints where each quote came from and how many round trips and handle lookups were needed.

        Returns:
            None: This method returns nothing.
        """
        identities = [
            {
                'instrument_id': INFY,
                'exchange': 'nse',
                'segment': 'nse_equities',
            },
            {
                'instrument_id': RELIANCE,
                'exchange': 'nse',
                'segment': 'nse_equities',
            },
        ]
        mapping_date = datetime.date(2026, 9, 15)
        answers = self.service.quotes(identities, mapping_date)
        for answer in answers:
            print(f'{answer["instrument_id"]}: last price {answer["last_price"]}, source {answer["source"]}')
        print(f'Redis round trips: {self.cache.round_trips}')
        single = self.service.quote(identities[1], mapping_date)
        print(f'Single quote for {single["instrument_id"]}: last price {single["last_price"]}, source {single["source"]}')
        print(f'Redis round trips in all: {self.cache.round_trips}')
        print(f'Broker handles looked up: {self.mapping_cache.lookups}')


if __name__ == '__main__':
    ServingQuotesFromTheCacheExample().run()
