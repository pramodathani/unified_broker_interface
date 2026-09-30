"""Writes one day's mapping into the Redis hashes and reads every part of it back.

This is what the daily warm and the readers do between them. The program publishes the mapping date, writes two identities, one Zerodha token that carries one of them, both instruments' order handles, and the seen dates, underlyings, additional attributes and segment counts that the warm streams in with `write_fields`. It then reads each hash back through the tier's own readers, which is the point of the class: the shape written and the shape read come from the same code.

A small in-memory stand-in replaces the Redis client. It keeps strings and hashes in dictionaries, records each key's expiry, and runs a pipeline's commands when the pipeline is executed, which is all the tier uses. Notice that `read_token_identifiers` gives back instrument ids rather than identities, that an instrument with no resolved underlying is simply absent, and that `has_additional_attributes` is what tells "this instrument has no attributes" apart from "the hash was never warmed". The warm identifier is a new random value on every run, so the program prints only that one was written.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/cache/MappingRedisTier/example_2_writing_and_reading_one_day.py
"""

import datetime
import decimal

from stock_brokers.instruments.mapping.utilities.cache import (
    MappingRedisConnection,
    MappingRedisTier,
)


class StandInPipeline:
    """A stand-in for a Redis pipeline that queues commands and runs them on execute.

    Attributes:
        redis_client (StandInRedis): The stand-in client the commands run against.
        queued (list): The queued commands, as (method, arguments) pairs.
    """

    def __init__(self, redis_client):
        """Builds an empty pipeline.

        Args:
            redis_client (StandInRedis): The stand-in client the commands run against.

        Returns:
            None: This method returns nothing.
        """
        self.redis_client = redis_client
        self.queued = []

    def set(self, key, value):
        """Queues a string write.

        Args:
            key (str): The key to write.
            value (str): The value to store.

        Returns:
            None: This method returns nothing.
        """
        self.queued.append((self.redis_client.set, (key, value)))

    def hset(self, key, mapping):
        """Queues a hash write.

        Args:
            key (str): The hash to write into.
            mapping (dict): The fields to write.

        Returns:
            None: This method returns nothing.
        """
        self.queued.append((self.redis_client.hset, (key, mapping)))

    def hmget(self, key, fields):
        """Queues a read of several hash fields.

        Args:
            key (str): The hash to read.
            fields (list): The fields to read.

        Returns:
            None: This method returns nothing.
        """
        self.queued.append((self.redis_client.hmget, (key, fields)))

    def expire(self, key, seconds):
        """Queues an expiry.

        Args:
            key (str): The key to expire.
            seconds (int): How long the key may live.

        Returns:
            None: This method returns nothing.
        """
        self.queued.append((self.redis_client.expire, (key, seconds)))

    def execute(self):
        """Runs every queued command in order.

        Returns:
            list: Each command's reply, in the order queued.
        """
        replies = []
        for method, arguments in self.queued:
            replies.append(method(*arguments))
        self.queued = []
        return replies


class StandInRedis:
    """A stand-in for a Redis client that keeps strings and hashes in dictionaries.

    Attributes:
        values (dict): Each key's value: a string, or a dict for a hash.
        expiries (dict): Each key's expiry in seconds, as last set.
    """

    def __init__(self):
        """Builds an empty stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.values = {}
        self.expiries = {}

    def pipeline(self, transaction=True):
        """Starts a pipeline.

        Args:
            transaction (bool): Ignored; the stand-in always runs commands in order.

        Returns:
            StandInPipeline: A new pipeline.
        """
        return StandInPipeline(self)

    def get(self, key):
        """Reads a string.

        Args:
            key (str): The key to read.

        Returns:
            str | None: The value, or None when the key is absent.
        """
        return self.values.get(key)

    def set(self, key, value):
        """Writes a string.

        Args:
            key (str): The key to write.
            value (str): The value to store.

        Returns:
            bool: Always True.
        """
        self.values[key] = value
        return True

    def exists(self, key):
        """Counts whether a key exists.

        Args:
            key (str): The key to test.

        Returns:
            int: 1 when the key exists, otherwise 0.
        """
        if key in self.values:
            return 1
        return 0

    def expire(self, key, seconds):
        """Records a key's expiry.

        Args:
            key (str): The key to expire.
            seconds (int): How long the key may live.

        Returns:
            bool: Always True.
        """
        self.expiries[key] = seconds
        return True

    def hset(self, key, mapping):
        """Writes fields into a hash.

        Args:
            key (str): The hash to write into.
            mapping (dict): The fields to write.

        Returns:
            int: The number of fields written.
        """
        stored = self.values.setdefault(key, {})
        stored.update(mapping)
        return len(mapping)

    def hmget(self, key, fields):
        """Reads several fields of a hash.

        Args:
            key (str): The hash to read.
            fields (list): The fields to read.

        Returns:
            list: Each field's value, or None where the field is absent.
        """
        stored = self.values.get(key, {})
        replies = []
        for field in fields:
            replies.append(stored.get(field))
        return replies

    def hgetall(self, key):
        """Reads a whole hash.

        Args:
            key (str): The hash to read.

        Returns:
            dict: The hash's fields, empty when the key is absent.
        """
        return dict(self.values.get(key, {}))


class WritingAndReadingOneDayExample:
    """Writes one mapping date's hashes through the tier and reads them back.

    Attributes:
        redis_client (StandInRedis): The stand-in Redis the tier writes into.
        tier (MappingRedisTier): The tier being shown.
        mapping_date (datetime.date): The mapping date written.
        future_identity (dict): The identity of one NIFTY future.
        index_identity (dict): The identity of the NIFTY 50 index.
    """

    FUTURE_ID = '7c1e9b20-4d3a-4f87-a6b5-0e2d9c8f1a44'
    INDEX_ID = '2b9d4e6f-8a1c-4e35-b7d2-5f0a3c6e9b18'

    def __init__(self):
        """Builds the tier around the stand-in and the two identities.

        Returns:
            None: This method returns nothing.
        """
        self.redis_client = StandInRedis()
        self.tier = MappingRedisTier(MappingRedisConnection(self.redis_client))
        self.mapping_date = datetime.date(2026, 9, 30)
        self.future_identity = {
            'instrument_id': self.FUTURE_ID,
            'exchange': 'nse',
            'segment': 'nse_equity_index_futures',
            'shape': 'future',
            'symbol': None,
            'underlying_symbol': 'NIFTY',
            'expiry_date': datetime.date(2026, 10, 27),
            'strike_price': None,
            'option_type': None,
            'mapping_date': self.mapping_date,
        }
        self.index_identity = {
            'instrument_id': self.INDEX_ID,
            'exchange': 'nse',
            'segment': 'nse_equity_indices',
            'shape': 'security',
            'symbol': 'NIFTY 50',
            'underlying_symbol': None,
            'expiry_date': None,
            'strike_price': None,
            'option_type': None,
            'mapping_date': self.mapping_date,
        }

    def write_day(self):
        """Writes every hash for the mapping date, publishing the date last as the warm does.

        Returns:
            None: This method returns nothing.
        """
        identities = {
            self.FUTURE_ID: self.future_identity,
            self.INDEX_ID: self.index_identity,
        }
        print(f'write_identities: {self.tier.write_identities(self.mapping_date, identities)}')
        candidates_by_token = {
            '13238018': [
                self.future_identity,
            ],
        }
        print(f'write_token_candidates: {self.tier.write_token_candidates(self.mapping_date, "zerodha", candidates_by_token)}')
        handles_by_instrument = {
            self.FUTURE_ID: {
                'zerodha': {
                    'broker_token': '13238018',
                    'order_symbol': 'NIFTY26OCTFUT',
                    'lot_size': '75',
                    'tick_size': '0.1',
                },
                'dhan': {
                    'broker_token': '52168',
                    'order_symbol': None,
                    'lot_size': '75',
                    'tick_size': '0.1',
                },
            },
        }
        print(f'write_order_handles: {self.tier.write_order_handles(self.mapping_date, handles_by_instrument)}')
        expiry_seconds = 3600
        seen_fields = {
            self.FUTURE_ID: self.tier.encode_seen(datetime.date(2026, 7, 1), self.mapping_date),
            self.INDEX_ID: self.tier.encode_seen(datetime.date(2024, 1, 2), self.mapping_date),
        }
        underlying_fields = {
            self.FUTURE_ID: self.INDEX_ID,
        }
        attribute_fields = {
            self.FUTURE_ID: self.tier.encode_additional_attributes({
                'dhan': {
                    'freeze_quantity': '1800',
                },
            }),
        }
        contract_size_fields = {
            self.FUTURE_ID: self.tier.encode_contract_size(decimal.Decimal('75'), 'confirmed', True),
        }
        segment_fields = {
            'nse_equity_index_futures': '1',
            'nse_equity_indices': '1',
        }
        written = 0
        written += self.tier.write_fields(self.tier.seen_key(self.mapping_date), seen_fields, expiry_seconds)
        written += self.tier.write_fields(self.tier.underlyings_key(self.mapping_date), underlying_fields, expiry_seconds)
        written += self.tier.write_fields(self.tier.additional_attributes_key(self.mapping_date), attribute_fields, expiry_seconds)
        written += self.tier.write_fields(self.tier.contract_sizes_key(self.mapping_date), contract_size_fields, expiry_seconds)
        written += self.tier.write_fields(self.tier.segments_key(self.mapping_date), segment_fields, expiry_seconds)
        print(f'write_fields wrote {written} fields in all')
        print(f'write_current_date: {self.tier.write_current_date(self.mapping_date)}')
        print(f'A warm identifier was written: {self.tier.warm_identifier_key() in self.redis_client.values}')

    def read_day(self):
        """Reads every hash back through the tier's readers and prints what came back.

        Returns:
            None: This method returns nothing.
        """
        both = [
            self.FUTURE_ID,
            self.INDEX_ID,
        ]
        print(f'read_current_date: {self.tier.read_current_date()!r}')
        print(f'read_segment_counts: {self.tier.read_segment_counts(self.mapping_date)}')
        identities = self.tier.read_identities(self.mapping_date, both)
        for instrument_identifier in both:
            identity = identities[instrument_identifier]
            print(f'read_identities: {identity["segment"]} {identity["symbol"] or identity["underlying_symbol"]} expiring {identity["expiry_date"]}')
        tokens = [
            '13238018',
            '99999999',
        ]
        print(f'read_token_identifiers: {self.tier.read_token_identifiers(self.mapping_date, "zerodha", tokens)}')
        handles = self.tier.read_order_handles(self.mapping_date, both)
        print(f'read_order_handles for the future: {handles[self.FUTURE_ID]}')
        print(f'Instruments with order handles: {len(handles)}')
        print(f'read_seen: {self.tier.read_seen(self.mapping_date, both)}')
        print(f'read_underlyings: {self.tier.read_underlyings(self.mapping_date, both)}')
        seen, underlyings = self.tier.read_seen_and_underlyings(self.mapping_date, both)
        print(f'read_seen_and_underlyings: {len(seen)} seen, {len(underlyings)} underlying')
        print(f'read_additional_attributes: {self.tier.read_additional_attributes(self.mapping_date, both)}')
        print(f'has_additional_attributes today: {self.tier.has_additional_attributes(self.mapping_date)}')
        yesterday = self.mapping_date - datetime.timedelta(days=1)
        print(f'has_additional_attributes yesterday: {self.tier.has_additional_attributes(yesterday)}')
        print(f'read_segment_counts yesterday: {self.tier.read_segment_counts(yesterday)}')
        print(f'Expiry set on the seen hash: {self.redis_client.expiries[self.tier.seen_key(self.mapping_date)]} seconds')

    def run(self):
        """Writes the day, then reads it back.

        Returns:
            None: This method returns nothing.
        """
        self.write_day()
        self.read_day()


if __name__ == '__main__':
    WritingAndReadingOneDayExample().run()
