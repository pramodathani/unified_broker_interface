"""Shows that an `InstrumentCache` drops everything at the midnight after it first kept anything, even when the marker has not changed.

The catalogue keys in Redis expire at midnight, so data kept in a worker's memory is trusted only until the midnight after it was first kept. The cache reads the time through its `now` method; this program uses a subclass whose `now` answers a time the program sets, so the output never depends on when it runs. The subclass changes nothing else.

The program keeps one instrument at 23:50, reads it at 23:59 and again at 00:01 the next day, with the same marker both times. It then calls `current_marker` and `drop_everything` directly, holding the cache's lock as their callers must, to show what each does on its own, and asks `next_midnight` for the midnight that ends a moment's day. No Redis is used.

Notice that `valid_until` is the midnight after 23:50, that the read at 00:01 finds nothing and sets a new `valid_until` a day later, and that `current_marker` answers False and forgets everything when the warm identifier is missing.

Run it from the project root:

    python examples/unified_broker_interface/utilities/instrument_cache/InstrumentCache/example_2_dropped_at_midnight.py
"""

import datetime

from unified_broker_interface.utilities.instrument_cache import (
    InstrumentCache,
)

INSTRUMENT_ID = '22222222-2222-5222-8222-000000000003'
MAPPING_DATE = '2026-09-30'
WARM = '5d41402abc4b2a76b9719d911017c592'


class SetClockInstrumentCache(InstrumentCache):
    """An `InstrumentCache` whose clock is set by the program instead of read from the system.

    Attributes:
        moment (datetime.datetime): The time `now` answers.
    """

    def __init__(self, moment):
        """Builds an empty cache whose clock reads a set time.

        Args:
            moment (datetime.datetime): The time to start at.

        Returns:
            None: This method returns nothing.
        """
        super().__init__()
        self.moment = moment

    def now(self):
        """The time the program set.

        Returns:
            datetime.datetime: The time.
        """
        return self.moment


class DroppedAtMidnightExample:
    """Keeps an instrument before midnight and reads it either side of midnight.

    Attributes:
        cache (SetClockInstrumentCache): The cache being shown.
    """

    def __init__(self):
        """Builds the cache with its clock at 23:50.

        Returns:
            None: This method returns nothing.
        """
        self.cache = SetClockInstrumentCache(datetime.datetime(2026, 9, 30, 23, 50))

    def read_at(self, moment):
        """Moves the clock and reads the instrument.

        Args:
            moment (datetime.datetime): The time to read at.

        Returns:
            None: This method returns nothing.
        """
        self.cache.moment = moment
        texts = self.cache.instrument(MAPPING_DATE, WARM, INSTRUMENT_ID)
        print(f'Read at {self.cache.now()}: {texts}; valid until {self.cache.valid_until}')

    def run(self):
        """Keeps an instrument, reads it either side of midnight, then shows the marker checks on their own.

        Returns:
            None: This method returns nothing.
        """
        self.cache.keep_instrument(
            MAPPING_DATE,
            WARM,
            INSTRUMENT_ID,
            '{"segment": "nse_equity_index_futures", "underlying_symbol": "NIFTY"}',
            '{"zerodha": {"broker_token": "35001", "lot_size": "75"}}',
            '{"units_per_lot": 75, "status": "agreed", "tradeable": true}',
        )
        print(f'Kept at {self.cache.now()}; valid until {self.cache.valid_until}')
        self.read_at(datetime.datetime(2026, 9, 30, 23, 59))
        self.read_at(datetime.datetime(2026, 10, 1, 0, 1))
        with self.cache.lock:
            usable = self.cache.current_marker(MAPPING_DATE, WARM)
            print(f'current_marker with the same marker: {usable}, marker {self.cache.marker}')
            usable = self.cache.current_marker(MAPPING_DATE, None)
            print(f'current_marker with no warm identifier: {usable}, marker {self.cache.marker}')
            self.cache.current_marker(MAPPING_DATE, WARM)
            self.cache.drop_everything()
            print(f'After drop_everything: marker {self.cache.marker}, valid until {self.cache.valid_until}')
        moment = datetime.datetime(2026, 12, 31, 18, 30)
        print(f'Midnight that ends {moment}: {self.cache.next_midnight(moment)}')


if __name__ == '__main__':
    DroppedAtMidnightExample().run()
