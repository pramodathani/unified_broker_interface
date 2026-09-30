"""Builds a small lookup on top of `ThreeTierLookup` and follows one key from Postgres into Redis and into process memory.

`ThreeTierLookup` holds the walk every mapping cache question shares: look in this process's own dictionary, then in Redis, then in Postgres, and copy each answer into the tiers above the one that had it. A subclass supplies only three methods, `read_from_redis`, `read_from_postgres` and `write_to_redis`. The three lookups in `cache.py` are such subclasses; this program writes a fourth, which answers an instrument id with its lot size, so the base class's own behaviour can be seen without the real tiers' detail.

The "Redis" and "Postgres" tiers here are two small stand-in classes holding dictionaries, because the base class never looks inside its tiers and only the subclass talks to them. Notice how the shared `statistics` counters move: the first `resolve` is answered by Postgres, the second by this process, and a second lookup, standing in for another process, is answered by Redis because the first one wrote its answer there. `remember`, `known`, `entry` and `reset` work on the process tier alone and never touch the other two.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/cache/ThreeTierLookup/example_1_a_lot_size_lookup.py
"""

import datetime

from stock_brokers.instruments.mapping.utilities.cache import (
    ThreeTierLookup,
)


class DictionaryTier:
    """A stand-in for a Redis or Postgres tier that holds lot sizes in a dictionary.

    Attributes:
        lot_sizes (dict): Each instrument id's lot size.
        reads (int): How many times the tier was read.
    """

    def __init__(self, lot_sizes):
        """Builds the tier.

        Args:
            lot_sizes (dict): Each instrument id's lot size.

        Returns:
            None: This method returns nothing.
        """
        self.lot_sizes = lot_sizes
        self.reads = 0

    def read(self, keys):
        """Reads the lot sizes of the keys this tier holds.

        Args:
            keys (list): The instrument ids to read.

        Returns:
            dict: Each held instrument id to an entry with its lot size.
        """
        self.reads += 1
        found = {}
        for key in keys:
            if key in self.lot_sizes:
                found[key] = {
                    'lot_size': self.lot_sizes[key],
                }
        return found

    def write(self, entries):
        """Stores entries' lot sizes.

        Args:
            entries (dict): Each instrument id to an entry with its lot size.

        Returns:
            bool: Always True.
        """
        for key, entry in entries.items():
            self.lot_sizes[key] = entry['lot_size']
        return True


class LotSizeLookup(ThreeTierLookup):
    """Instrument id to that instrument's lot size, through the three tiers."""

    def read_from_redis(self, mapping_date, keys):
        """Reads lot sizes out of the Redis stand-in.

        Args:
            mapping_date (datetime.date): The mapping date to read.
            keys (list): The instrument ids to read.

        Returns:
            dict: Each held instrument id to its entry.
        """
        return self.redis_tier.read(keys)

    def read_from_postgres(self, mapping_date, keys):
        """Reads lot sizes out of the Postgres stand-in.

        Args:
            mapping_date (datetime.date): The mapping date to read.
            keys (list): The instrument ids to read.

        Returns:
            dict: Each held instrument id to its entry.
        """
        return self.postgres_tier.read(keys)

    def write_to_redis(self, mapping_date, entries):
        """Writes lot sizes into the Redis stand-in.

        Args:
            mapping_date (datetime.date): The mapping date the entries belong to.
            entries (dict): Each instrument id to its entry.

        Returns:
            bool: True when the write went through.
        """
        return self.redis_tier.write(entries)


class LotSizeLookupExample:
    """Resolves lot sizes through a first and a second lookup sharing one Redis stand-in.

    Attributes:
        mapping_date (datetime.date): The mapping date asked about.
        redis_tier (DictionaryTier): The Redis stand-in, empty at first.
        postgres_tier (DictionaryTier): The Postgres stand-in, holding every lot size.
        statistics (dict): The counters the lookups share.
        lookup (LotSizeLookup): The first process's lookup.
    """

    def __init__(self):
        """Builds the tiers, the counters and the first lookup.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 9, 30)
        self.redis_tier = DictionaryTier({})
        self.postgres_tier = DictionaryTier({
            'nifty-future': '75',
            'banknifty-future': '35',
            'crudeoil-future': '100',
        })
        self.statistics = {
            'process_hits': 0,
            'redis_hits': 0,
            'postgres_hits': 0,
            'misses': 0,
        }
        self.lookup = LotSizeLookup(self.redis_tier, self.postgres_tier, self.statistics)

    def run(self):
        """Resolves the same keys cold, warm and from a second lookup, then uses the process tier directly.

        Returns:
            None: This method returns nothing.
        """
        keys = [
            'nifty-future',
            'banknifty-future',
        ]
        print(f'First resolve: {self.lookup.resolve(self.mapping_date, keys)}')
        print(f'  counters: {self.statistics}')
        print(f'Second resolve: {self.lookup.resolve(self.mapping_date, keys)}')
        print(f'  counters: {self.statistics}')
        print(f'Redis now holds: {self.redis_tier.lot_sizes}')
        second_process = LotSizeLookup(self.redis_tier, self.postgres_tier, self.statistics)
        print(f'Second process resolves: {second_process.resolve(self.mapping_date, keys)}')
        print(f'  counters: {self.statistics}')
        print(f'Postgres was read {self.postgres_tier.reads} time')
        print(f'Known before remember: {self.lookup.known("crudeoil-future")}')
        crude_entry = {
            'lot_size': '100',
        }
        self.lookup.remember('crudeoil-future', crude_entry)
        print(f'Known after remember: {self.lookup.known("crudeoil-future")}')
        print(f'Entry held for it: {self.lookup.entry("crudeoil-future")}')
        print(f'Entry for a key never seen: {self.lookup.entry("goldm-future")}')
        print(f'What a miss is remembered as: {self.lookup.empty_entry()}')
        crude_only = [
            'crudeoil-future',
        ]
        print(f'Reading Redis directly: {self.lookup.read_from_redis(self.mapping_date, crude_only)}')
        print(f'Reading Postgres directly: {self.lookup.read_from_postgres(self.mapping_date, crude_only)}')
        crude_entries = {
            'crudeoil-future': crude_entry,
        }
        print(f'Writing Redis directly: {self.lookup.write_to_redis(self.mapping_date, crude_entries)}')
        self.lookup.reset()
        print(f'Known after reset: {self.lookup.known("nifty-future")}')


if __name__ == '__main__':
    LotSizeLookupExample().run()
