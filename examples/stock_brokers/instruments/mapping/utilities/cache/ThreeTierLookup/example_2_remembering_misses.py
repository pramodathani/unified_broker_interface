"""Shows what the base class does on its own, and how `empty_entry` decides whether a miss is asked about again.

`ThreeTierLookup` is meant to be subclassed. Used directly, its three tier methods raise `NotImplementedError` naming the class, while an empty batch of keys is answered without reaching any tier at all.

The more interesting choice a subclass makes is `empty_entry`. When Postgres has no answer for a key, the walk asks `empty_entry()` what to remember. The base answer, None, remembers nothing, so the next look-up of that key goes all the way to Postgres again; the cache's identity lookup works this way, because an unknown instrument id is a caller's mistake that tomorrow's master may fix. A subclass that returns an empty value instead makes the miss a fact for the rest of the day; the cache's token lookup works this way, because a token a broker does not carry is asked about on every tick.

This program builds two small subclasses that differ only in `empty_entry` and asks each about the same unknown key three times, against a stand-in Postgres that counts its reads. Notice that the first asks Postgres three times and the second once.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/cache/ThreeTierLookup/example_2_remembering_misses.py
"""

import datetime

from stock_brokers.instruments.mapping.utilities.cache import (
    ThreeTierLookup,
)


class CountingEmptyTier:
    """A stand-in tier that holds nothing and counts how often it is read.

    Attributes:
        reads (int): How many times the tier was read.
    """

    def __init__(self):
        """Builds the tier with no reads counted.

        Returns:
            None: This method returns nothing.
        """
        self.reads = 0

    def read(self, keys):
        """Counts one read and finds nothing.

        Args:
            keys (list): The keys asked about.

        Returns:
            dict: Always empty.
        """
        self.reads += 1
        return {}


class ForgettingLookup(ThreeTierLookup):
    """A lookup that keeps the base class's `empty_entry`, so it never remembers a miss."""

    def read_from_redis(self, mapping_date, keys):
        """Reads the Redis stand-in.

        Args:
            mapping_date (datetime.date): The mapping date to read.
            keys (list): The keys to read.

        Returns:
            dict: What the stand-in held.
        """
        return self.redis_tier.read(keys)

    def read_from_postgres(self, mapping_date, keys):
        """Reads the Postgres stand-in.

        Args:
            mapping_date (datetime.date): The mapping date to read.
            keys (list): The keys to read.

        Returns:
            dict: What the stand-in held.
        """
        return self.postgres_tier.read(keys)

    def write_to_redis(self, mapping_date, entries):
        """Accepts entries without storing them.

        Args:
            mapping_date (datetime.date): The mapping date the entries belong to.
            entries (dict): The entries to write.

        Returns:
            bool: Always True.
        """
        return True


class RememberingLookup(ForgettingLookup):
    """A lookup that remembers a miss as an empty list for the rest of the day."""

    def empty_entry(self):
        """What to remember for a key nothing maps.

        Returns:
            list: A new empty list.
        """
        return []


class RememberingMissesExample:
    """Calls the base class directly, then compares a forgetting and a remembering lookup.

    Attributes:
        mapping_date (datetime.date): The mapping date asked about.
        statistics (dict): The counters the lookups count into.
    """

    def __init__(self):
        """Builds the date and the counters.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 9, 30)
        self.statistics = {
            'process_hits': 0,
            'redis_hits': 0,
            'postgres_hits': 0,
            'misses': 0,
        }

    def show_base_class(self):
        """Calls each method of the base class itself and prints what happens.

        Returns:
            None: This method returns nothing.
        """
        base = ThreeTierLookup(None, None, self.statistics)
        print(f'Base resolve of no keys: {base.resolve(self.mapping_date, [])}')
        print(f'Base empty_entry: {base.empty_entry()}')
        keys = [
            '999999',
        ]
        try:
            base.resolve(self.mapping_date, keys)
        except NotImplementedError as error:
            print(f'Base resolve of a key: NotImplementedError: {error}')
        try:
            base.read_from_redis(self.mapping_date, keys)
        except NotImplementedError as error:
            print(f'Base read_from_redis: NotImplementedError: {error}')
        try:
            base.read_from_postgres(self.mapping_date, keys)
        except NotImplementedError as error:
            print(f'Base read_from_postgres: NotImplementedError: {error}')
        try:
            base.write_to_redis(self.mapping_date, {})
        except NotImplementedError as error:
            print(f'Base write_to_redis: NotImplementedError: {error}')

    def ask_three_times(self, lookup, postgres_tier):
        """Asks one lookup about an unknown key three times and prints the result.

        Args:
            lookup (ThreeTierLookup): The lookup to ask.
            postgres_tier (CountingEmptyTier): The Postgres stand-in behind it.

        Returns:
            None: This method returns nothing.
        """
        keys = [
            '999999',
        ]
        answers = []
        for attempt in range(3):
            answers.append(lookup.resolve(self.mapping_date, keys))
        name = type(lookup).__name__
        print(f'{name}: answers {answers}, Postgres read {postgres_tier.reads} times, remembered: {lookup.known("999999")}')

    def run(self):
        """Shows the base class, then the two lookups side by side.

        Returns:
            None: This method returns nothing.
        """
        self.show_base_class()
        forgetting_postgres = CountingEmptyTier()
        forgetting = ForgettingLookup(CountingEmptyTier(), forgetting_postgres, self.statistics)
        self.ask_three_times(forgetting, forgetting_postgres)
        remembering_postgres = CountingEmptyTier()
        remembering = RememberingLookup(CountingEmptyTier(), remembering_postgres, self.statistics)
        self.ask_three_times(remembering, remembering_postgres)
        print(f'Counters: {self.statistics}')


if __name__ == '__main__':
    RememberingMissesExample().run()
