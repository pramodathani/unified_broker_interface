"""Shows every read and write of the mapping tier degrading quietly when Redis cannot be reached.

The mapping cache sits in front of data that Postgres still holds, so a Redis that is down must never turn an order into an error. Every method of `MappingRedisTier` asks its connection for a client first, and when the answer is None it returns an empty answer: None or an empty dictionary for a read, False or zero for a write. The caller then falls through to Postgres.

This program builds the tier with no client of its own and points `redis_configuration` at port 9 on this machine, where nothing listens, so the first call fails to connect and every later call inside the retry window gets None without trying again. Notice that `failed_connections` stays at one however many calls are made, and that the empty reads keep their usual types, so a caller needs no special case beyond the ones it already has.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/cache/MappingRedisTier/example_4_when_redis_is_down.py
"""

import datetime

from stock_brokers.instruments.mapping.utilities.cache import (
    MappingRedisTier,
)
from utilities.configurations import redis_configuration


class WhenRedisIsDownExample:
    """Calls each Redis read and write of the tier while Redis is unreachable.

    Attributes:
        tier (MappingRedisTier): The tier being shown, with a connection it opens itself.
        mapping_date (datetime.date): The mapping date asked about.
        instrument_identifiers (list): The instrument ids asked about.
    """

    def __init__(self):
        """Points the Redis configuration at a closed port and builds the tier.

        Returns:
            None: This method returns nothing.
        """
        redis_configuration['host'] = '127.0.0.1'
        redis_configuration['port'] = 9
        self.tier = MappingRedisTier()
        self.mapping_date = datetime.date(2026, 9, 30)
        self.instrument_identifiers = [
            '0a6e2d41-9c7f-4b58-8d13-6f2e4a9b7c05',
        ]

    def show_reads(self):
        """Prints what each read answers while Redis is down.

        Returns:
            None: This method returns nothing.
        """
        tokens = [
            '408065',
        ]
        segment_prefixes = [
            ('nse_equities', 'INFY|'),
        ]
        print(f'read_current_date: {self.tier.read_current_date()}')
        print(f'read_segment_counts: {self.tier.read_segment_counts(self.mapping_date)}')
        print(f'read_catalogue: {self.tier.read_catalogue(self.mapping_date, "nse_equities", 0, 9)}')
        print(f'read_catalogue_for_prefix: {self.tier.read_catalogue_for_prefix(self.mapping_date, "nse_equities", "INFY|", 5)}')
        print(f'read_catalogue_for_prefixes: {self.tier.read_catalogue_for_prefixes(self.mapping_date, segment_prefixes)}')
        print(f'read_names: {self.tier.read_names(self.mapping_date, "nse_equities")}')
        print(f'read_identities: {self.tier.read_identities(self.mapping_date, self.instrument_identifiers)}')
        print(f'read_token_identifiers: {self.tier.read_token_identifiers(self.mapping_date, "zerodha", tokens)}')
        print(f'read_order_handles: {self.tier.read_order_handles(self.mapping_date, self.instrument_identifiers)}')
        print(f'read_seen: {self.tier.read_seen(self.mapping_date, self.instrument_identifiers)}')
        print(f'read_underlyings: {self.tier.read_underlyings(self.mapping_date, self.instrument_identifiers)}')
        print(f'read_seen_and_underlyings: {self.tier.read_seen_and_underlyings(self.mapping_date, self.instrument_identifiers)}')
        print(f'read_additional_attributes: {self.tier.read_additional_attributes(self.mapping_date, self.instrument_identifiers)}')
        print(f'has_additional_attributes: {self.tier.has_additional_attributes(self.mapping_date)}')

    def show_writes(self):
        """Prints what each write answers while Redis is down.

        Returns:
            None: This method returns nothing.
        """
        identities = {
            self.instrument_identifiers[0]: {
                'instrument_id': self.instrument_identifiers[0],
            },
        }
        handles = {
            self.instrument_identifiers[0]: {
                'zerodha': {
                    'broker_token': '408065',
                    'order_symbol': 'INFY',
                    'lot_size': '1',
                    'tick_size': '0.1',
                },
            },
        }
        fields = {
            self.instrument_identifiers[0]: '2024-01-02|2026-09-30',
        }
        members_by_key = {
            self.tier.names_key(self.mapping_date, 'nse_equities'): [
                'INFY',
            ],
        }
        print(f'write_current_date: {self.tier.write_current_date(self.mapping_date)}')
        print(f'write_identities: {self.tier.write_identities(self.mapping_date, identities)}')
        print(f'write_token_candidates: {self.tier.write_token_candidates(self.mapping_date, "zerodha", {})}')
        print(f'write_order_handles: {self.tier.write_order_handles(self.mapping_date, handles)}')
        print(f'write_fields: {self.tier.write_fields(self.tier.seen_key(self.mapping_date), fields, 60)}')
        print(f'write_members: {self.tier.write_members(members_by_key, 60)}')
        print(f'clear_other_dates: {self.tier.clear_other_dates(self.mapping_date)}')

    def run(self):
        """Shows the reads, then the writes, then how many connection attempts failed.

        Returns:
            None: This method returns nothing.
        """
        self.show_reads()
        self.show_writes()
        print(f'Failed connection attempts: {self.tier.connection.failed_connections}')


if __name__ == '__main__':
    WhenRedisIsDownExample().run()
