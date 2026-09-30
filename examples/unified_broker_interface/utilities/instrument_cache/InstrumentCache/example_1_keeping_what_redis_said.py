"""Keeps an instrument's catalogue data in a worker's memory and finds it again, until the catalogue is warmed again.

The order routes read an instrument's identity, order handles and contract size decision from Redis before they place or modify an order. That data does not change during a day's warm, so each gunicorn worker keeps what it read in an `InstrumentCache` and skips the Redis read next time. Everything is kept under a marker, the mapping date and warm identifier Redis held when it was read, and every lookup passes the marker Redis holds now. When they differ, because the catalogue was warmed again, everything kept is dropped.

This program plays the part of the order route. It keeps one instrument, one segment-and-name lookup and one broker token's candidates under the morning's marker, reads them back, and then reads again with a new warm identifier. It also shows that nothing is kept while Redis holds no warm identifier. The texts kept are short examples of what Redis holds; the cache stores them as they are without reading them. No Redis is used, because the cache is handed the marker directly.

Notice that the three reads find what was kept, that the first read under the new warm identifier finds nothing and forgets the rest too, and that keeping under a missing warm identifier keeps nothing.

Run it from the project root:

    python examples/unified_broker_interface/utilities/instrument_cache/InstrumentCache/example_1_keeping_what_redis_said.py
"""

from unified_broker_interface.utilities.instrument_cache import (
    InstrumentCache,
)

INSTRUMENT_ID = '22222222-2222-5222-8222-000000000001'
MAPPING_DATE = '2026-09-30'
MORNING_WARM = '5d41402abc4b2a76b9719d911017c592'
EVENING_WARM = '7d793037a0760186574b0282f2f435e7'


class KeepingWhatRedisSaidExample:
    """Keeps and reads back catalogue data under two warm identifiers.

    Attributes:
        cache (InstrumentCache): The cache being shown.
    """

    def __init__(self):
        """Builds an empty cache.

        Returns:
            None: This method returns nothing.
        """
        self.cache = InstrumentCache()

    def keep_morning_data(self):
        """Keeps one instrument, one lookup and one token's candidates under the morning's marker.

        Returns:
            None: This method returns nothing.
        """
        self.cache.keep_instrument(
            MAPPING_DATE,
            MORNING_WARM,
            INSTRUMENT_ID,
            '{"segment": "nse_equities", "symbol": "INFY"}',
            '{"zerodha": {"broker_token": "408065", "lot_size": "1"}}',
            None,
        )
        self.cache.keep_instrument_lookup(MAPPING_DATE, MORNING_WARM, 'nse_equities', 'INFY|', INSTRUMENT_ID)
        self.cache.keep_token_candidates(MAPPING_DATE, MORNING_WARM, 'zerodha', '408065', INSTRUMENT_ID)

    def read_all(self, warm_identifier):
        """Reads the instrument, the lookup and the token's candidates under one warm identifier.

        Args:
            warm_identifier (str | None): The warm identifier Redis holds now.

        Returns:
            None: This method returns nothing.
        """
        texts = self.cache.instrument(MAPPING_DATE, warm_identifier, INSTRUMENT_ID)
        print(f'  instrument: {texts}')
        found = self.cache.instrument_lookup(MAPPING_DATE, warm_identifier, 'nse_equities', 'INFY|')
        print(f'  lookup of INFY: {found}')
        candidates = self.cache.token_candidates_text(MAPPING_DATE, warm_identifier, 'zerodha', '408065')
        print(f'  zerodha token 408065: {candidates}')

    def run(self):
        """Keeps the morning's data, reads it back, then reads under a new warm and with no warm.

        Returns:
            None: This method returns nothing.
        """
        print(f'Largest store size: {InstrumentCache.MAXIMUM_ENTRIES}')
        print(f'The clock answers a {type(self.cache.now()).__name__}')
        self.keep_morning_data()
        print(f'Kept under {self.cache.marker}')
        print('Read under the same marker:')
        self.read_all(MORNING_WARM)
        print('Read after the catalogue was warmed again:')
        self.read_all(EVENING_WARM)
        print(f'Instruments kept now: {len(self.cache.instrument_texts)}, marker {self.cache.marker}')
        self.cache.keep_instrument(MAPPING_DATE, None, INSTRUMENT_ID, '{}', '{}', None)
        print(f'After keeping with no warm identifier: {len(self.cache.instrument_texts)} kept, marker {self.cache.marker}')


if __name__ == '__main__':
    KeepingWhatRedisSaidExample().run()
