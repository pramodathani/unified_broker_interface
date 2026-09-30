"""Builds a small option catalogue in Redis and searches it by name, expiry, strike and option type.

The catalogue is one sorted set per segment in which every member has the score zero, so Redis keeps the members in plain text order. Each member is laid out as name, expiry, strike, option type and instrument id, so text order is also the order a person would want to browse contracts in, and every contract under one name, or one expiry, sits in a single range that starts with a known prefix. A second sorted set per segment lists only the distinct names, which is what a search box scans.

This program writes six NIFTY and BANKNIFTY options and their two names with `write_members`, then reads them back four ways: a slice by position, every contract under a prefix, the first contract under each of several prefixes in one round trip, and the list of names. Finally it leaves a stale key from the day before in Redis and calls `clear_other_dates`, which deletes every dated key except the kept date's and the two undated keys.

A small in-memory stand-in replaces the Redis client. It keeps each sorted set as a Python set and sorts it on every read, which gives the same order as Redis for members made of plain text. Notice that the 900 strike sorts before the 1000 strike, which is only true because the tier zero-pads strikes, and that a prefix nothing starts with reads as None in the batched form.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/cache/MappingRedisTier/example_3_searching_the_catalogue.py
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

    def zadd(self, key, mapping):
        """Queues adding members to a sorted set.

        Args:
            key (str): The sorted set.
            mapping (dict): Each member to its score.

        Returns:
            None: This method returns nothing.
        """
        self.queued.append((self.redis_client.zadd, (key, mapping)))

    def expire(self, key, seconds):
        """Queues an expiry.

        Args:
            key (str): The key to expire.
            seconds (int): How long the key may live.

        Returns:
            None: This method returns nothing.
        """
        self.queued.append((self.redis_client.expire, (key, seconds)))

    def zrangebylex(self, key, minimum, maximum, start=None, num=None):
        """Queues a read of a sorted set's members between two text bounds.

        Args:
            key (str): The sorted set.
            minimum (bytes): The lower bound, starting with "[" for inclusive.
            maximum (bytes): The upper bound, starting with "(" for exclusive.
            start (int | None): How many matching members to skip.
            num (int | None): The most members to return.

        Returns:
            None: This method returns nothing.
        """
        self.queued.append((self.redis_client.zrangebylex, (key, minimum, maximum, start, num)))

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
    """A stand-in for a Redis client that keeps strings and sorted sets in memory.

    Attributes:
        values (dict): Each key's value: a string, or a set of members for a sorted set.
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

    def zadd(self, key, mapping):
        """Adds members to a sorted set; every score here is zero, so only the members are kept.

        Args:
            key (str): The sorted set.
            mapping (dict): Each member to its score.

        Returns:
            int: The number of members given.
        """
        members = self.values.setdefault(key, set())
        for member in mapping:
            members.add(member)
        return len(mapping)

    def zrange(self, key, start, stop):
        """Reads a sorted set's members by position, in text order.

        Args:
            key (str): The sorted set.
            start (int): The first position.
            stop (int): The last position, inclusive, or -1 for the end.

        Returns:
            list: The members.
        """
        ordered = sorted(self.values.get(key, set()))
        if stop == -1:
            return ordered[start:]
        return ordered[start:stop + 1]

    def zrangebylex(self, key, minimum, maximum, start=None, num=None):
        """Reads a sorted set's members between an inclusive lower and an exclusive upper text bound.

        Args:
            key (str): The sorted set.
            minimum (bytes): The lower bound, starting with "[".
            maximum (bytes): The upper bound, starting with "(".
            start (int | None): How many matching members to skip.
            num (int | None): The most members to return.

        Returns:
            list: The matching members, in text order.
        """
        lower = minimum[1:]
        upper = maximum[1:]
        matching = []
        for member in sorted(self.values.get(key, set())):
            encoded = member.encode()
            if lower <= encoded < upper:
                matching.append(member)
        first = start or 0
        if num is None:
            return matching[first:]
        return matching[first:first + num]

    def scan_iter(self, match):
        """Lists the keys that start with a pattern's text before its closing "*".

        Args:
            match (str): A pattern ending in "*".

        Returns:
            list: The matching keys, sorted.
        """
        prefix = match.rstrip('*')
        found = []
        for key in sorted(self.values):
            if key.startswith(prefix):
                found.append(key)
        return found

    def delete(self, key):
        """Deletes a key.

        Args:
            key (str): The key to delete.

        Returns:
            int: 1 when the key existed, otherwise 0.
        """
        if key in self.values:
            del self.values[key]
            return 1
        return 0


class SearchingTheCatalogueExample:
    """Writes an option catalogue and searches it through the tier.

    Attributes:
        redis_client (StandInRedis): The stand-in Redis the tier writes into.
        tier (MappingRedisTier): The tier being shown.
        mapping_date (datetime.date): The mapping date of the catalogue.
        segment (str): The segment the options belong to.
        labels (dict): Each written instrument id to a readable description of the contract.
    """

    def __init__(self):
        """Builds the tier around the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.redis_client = StandInRedis()
        self.tier = MappingRedisTier(MappingRedisConnection(self.redis_client))
        self.mapping_date = datetime.date(2026, 9, 30)
        self.segment = 'nse_equity_index_options'
        self.labels = {}

    def option(self, instrument_identifier, underlying_symbol, expiry_date, strike_price, option_type):
        """Builds one option's identity.

        Args:
            instrument_identifier (str): The instrument id.
            underlying_symbol (str): The underlying's symbol.
            expiry_date (datetime.date): The expiry.
            strike_price (str): The strike, as text.
            option_type (str): "CE" or "PE".

        Returns:
            dict: The identity.
        """
        return {
            'instrument_id': instrument_identifier,
            'exchange': 'nse',
            'segment': self.segment,
            'shape': 'option',
            'symbol': None,
            'underlying_symbol': underlying_symbol,
            'expiry_date': expiry_date,
            'strike_price': decimal.Decimal(strike_price),
            'option_type': option_type,
            'mapping_date': self.mapping_date,
        }

    def write_catalogue(self):
        """Writes six options and their two names into the catalogue and names sets.

        Returns:
            None: This method returns nothing.
        """
        first_expiry = datetime.date(2026, 10, 6)
        second_expiry = datetime.date(2026, 10, 13)
        options = [
            self.option('00000000-0000-4000-8000-000000000001', 'NIFTY', first_expiry, '1000', 'CE'),
            self.option('00000000-0000-4000-8000-000000000002', 'NIFTY', first_expiry, '900', 'PE'),
            self.option('00000000-0000-4000-8000-000000000003', 'NIFTY', first_expiry, '900', 'CE'),
            self.option('00000000-0000-4000-8000-000000000004', 'NIFTY', second_expiry, '25000', 'CE'),
            self.option('00000000-0000-4000-8000-000000000005', 'BANKNIFTY', first_expiry, '55000', 'PE'),
            self.option('00000000-0000-4000-8000-000000000006', 'BANKNIFTY', second_expiry, '55000', 'CE'),
        ]
        catalogue_members = []
        name_members = []
        for identity in options:
            self.labels[identity['instrument_id']] = f'{identity["underlying_symbol"]} {identity["expiry_date"]} {identity["strike_price"]} {identity["option_type"]}'
            catalogue_members.append(self.tier.encode_catalogue_member(identity))
            name = self.tier.catalogue_name(identity)
            if name not in name_members:
                name_members.append(name)
        members_by_key = {
            self.tier.catalogue_key(self.mapping_date, self.segment): catalogue_members,
            self.tier.names_key(self.mapping_date, self.segment): name_members,
        }
        sent = self.tier.write_members(members_by_key, 3600)
        print(f'write_members sent {sent} members')

    def search(self):
        """Reads the catalogue back by position, by prefix, by several prefixes, and by name.

        Returns:
            None: This method returns nothing.
        """
        print('read_catalogue, the first four in order:')
        for instrument_identifier in self.tier.read_catalogue(self.mapping_date, self.segment, 0, 3):
            print(f'  {instrument_identifier} {self.labels[instrument_identifier]}')
        nifty_first_expiry = self.tier.catalogue_prefix('NIFTY', datetime.date(2026, 10, 6))
        print(f'read_catalogue_for_prefix {nifty_first_expiry}:')
        for instrument_identifier in self.tier.read_catalogue_for_prefix(self.mapping_date, self.segment, nifty_first_expiry, 10):
            print(f'  {instrument_identifier} {self.labels[instrument_identifier]}')
        segment_prefixes = [
            (self.segment, self.tier.catalogue_prefix('BANKNIFTY', datetime.date(2026, 10, 13), decimal.Decimal('55000'), 'CE')),
            (self.segment, self.tier.catalogue_prefix('NIFTY', datetime.date(2026, 10, 6), decimal.Decimal('900'), 'CE')),
            (self.segment, self.tier.catalogue_prefix('FINNIFTY')),
        ]
        print(f'read_catalogue_for_prefixes: {self.tier.read_catalogue_for_prefixes(self.mapping_date, segment_prefixes)}')
        print(f'read_names: {self.tier.read_names(self.mapping_date, self.segment)}')

    def clear_yesterday(self):
        """Leaves a key from the day before and clears every date but today's.

        Returns:
            None: This method returns nothing.
        """
        yesterday = self.mapping_date - datetime.timedelta(days=1)
        self.redis_client.set(self.tier.current_date_key(), self.mapping_date.isoformat())
        stale_names = {
            'NIFTY': 0,
        }
        self.redis_client.zadd(self.tier.names_key(yesterday, self.segment), stale_names)
        print(f'Keys before clear_other_dates: {len(self.redis_client.scan_iter(self.tier.KEY_PREFIX + "*"))}')
        print(f'clear_other_dates deleted: {self.tier.clear_other_dates(self.mapping_date)}')
        for key in self.redis_client.scan_iter(self.tier.KEY_PREFIX + '*'):
            print(f'  kept {key}')

    def run(self):
        """Writes the catalogue, searches it, then clears the stale date.

        Returns:
            None: This method returns nothing.
        """
        self.write_catalogue()
        self.search()
        self.clear_yesterday()


if __name__ == '__main__':
    SearchingTheCatalogueExample().run()
