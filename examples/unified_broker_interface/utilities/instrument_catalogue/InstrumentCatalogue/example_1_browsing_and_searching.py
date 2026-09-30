"""Lists the segments, lists every NSE instrument and searches the NSE index options, all from the mapping cache's Redis tier.

An `InstrumentCatalogue` answers `/api/instruments/segments`, `/master` and `/search`. It reads the Redis tier the daily warm fills: a hash of instrument counts per segment, which also says the day's catalogue is complete, one sorted set of catalogue members per segment in name, expiry, strike and option type order, one sorted set of distinct names per segment, and a hash of identities. Postgres is read only for a past date or a cold cache, which this program does not ask about.

This program builds a real `MappingCache` around two stand-ins. The Redis stand-in holds keys in dictionaries and answers the handful of commands the tier reads with; it is filled through the tier's own encoders, so the keys and values are laid out exactly as a warm writes them. The database stand-in refuses every connection, which proves that nothing here falls back to Postgres. The catalogue holds two stocks, a NIFTY future and four index options for 2026-09-30.

Notice the segments in the canonical order with each one's identity fields, and the listing in the byte order of the catalogue members. That order puts NIFTYNXT50 before NIFTY, because a member is the name followed by `|`, which sorts after every letter. Notice too that a search for `nifty` lists the exact name NIFTY first, then NIFTYNXT50, which starts with it, then BANKNIFTY, which only contains it.

Run it from the project root:

    python examples/unified_broker_interface/utilities/instrument_catalogue/InstrumentCatalogue/example_1_browsing_and_searching.py
"""

import datetime
import decimal

from stock_brokers.instruments.mapping.utilities.cache import (
    MappingCache,
    MappingRedisConnection,
    MappingRedisTier,
)
from unified_broker_interface.utilities.instrument_catalogue import (
    InstrumentCatalogue,
)

MAPPING_DATE = datetime.date(2026, 9, 30)


class CatalogueRedis:
    """A stand-in for the Redis client that answers the reads the mapping cache's Redis tier makes.

    Attributes:
        strings (dict): String values by key.
        hashes (dict): Hashes by key, each a dict of field to value.
        sorted_sets (dict): Sorted sets by key, each a list of members, all with the score zero.
    """

    def __init__(self):
        """Builds an empty stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.strings = {}
        self.hashes = {}
        self.sorted_sets = {}

    def get(self, key):
        """Reads a string.

        Args:
            key (str): The key.

        Returns:
            str | None: The value, or None when the key is missing.
        """
        return self.strings.get(key)

    def exists(self, key):
        """Counts whether a key exists.

        Args:
            key (str): The key.

        Returns:
            int: 1 when it exists, otherwise 0.
        """
        if key in self.strings or key in self.hashes or key in self.sorted_sets:
            return 1
        return 0

    def hgetall(self, key):
        """Reads a whole hash.

        Args:
            key (str): The key.

        Returns:
            dict: The hash, empty when the key is missing.
        """
        return dict(self.hashes.get(key, {}))

    def hmget(self, key, fields):
        """Reads several fields of a hash.

        Args:
            key (str): The key.
            fields (list): The fields.

        Returns:
            list: One value or None per field, in order.
        """
        stored = self.hashes.get(key, {})
        values = []
        for field in fields:
            values.append(stored.get(field))
        return values

    def zrange(self, key, start, stop):
        """Reads a slice of a sorted set whose members all score zero, so the order is lexical.

        Args:
            key (str): The key.
            start (int): The first position.
            stop (int): The last position, inclusive, where -1 means the end.

        Returns:
            list: The members as bytes.
        """
        members = sorted(self.sorted_sets.get(key, []))
        if stop == -1:
            chosen = members[start:]
        else:
            chosen = members[start:stop + 1]
        encoded = []
        for member in chosen:
            encoded.append(member.encode())
        return encoded

    def zrangebylex(self, key, minimum, maximum, start=None, num=None):
        """Reads the members of a sorted set between two lexical bounds.

        Args:
            key (str): The key.
            minimum (bytes): The lower bound, starting with `[` for an inclusive bound.
            maximum (bytes): The upper bound, starting with `(` for an exclusive bound.
            start (int | None): How many matching members to skip.
            num (int | None): The most members to return.

        Returns:
            list: The members as bytes.
        """
        lower = minimum[1:]
        upper = maximum[1:]
        found = []
        for member in sorted(self.sorted_sets.get(key, [])):
            encoded = member.encode()
            if lower <= encoded < upper:
                found.append(encoded)
        first = start or 0
        if num is None:
            return found[first:]
        return found[first:first + num]

    def pipeline(self, transaction=True):
        """Starts a pipeline.

        Args:
            transaction (bool): Accepted as redis-py does and ignored.

        Returns:
            CataloguePipeline: The pipeline.
        """
        del transaction
        return CataloguePipeline(self)


class CataloguePipeline:
    """A stand-in pipeline that queues reads and runs them together.

    Attributes:
        client (CatalogueRedis): The stand-in the reads run against.
        queued (list): The queued reads, as pairs of a method and its arguments.
    """

    def __init__(self, client):
        """Builds an empty pipeline.

        Args:
            client (CatalogueRedis): The stand-in the reads run against.

        Returns:
            None: This method returns nothing.
        """
        self.client = client
        self.queued = []

    def hmget(self, key, fields):
        """Queues a read of several hash fields.

        Args:
            key (str): The key.
            fields (list): The fields.

        Returns:
            CataloguePipeline: This pipeline.
        """
        self.queued.append((
            self.client.hmget,
            (
                key,
                fields,
            ),
        ))
        return self

    def zrangebylex(self, key, minimum, maximum, start=None, num=None):
        """Queues a lexical range read.

        Args:
            key (str): The key.
            minimum (bytes): The lower bound.
            maximum (bytes): The upper bound.
            start (int | None): How many matching members to skip.
            num (int | None): The most members to return.

        Returns:
            CataloguePipeline: This pipeline.
        """
        self.queued.append((
            self.client.zrangebylex,
            (
                key,
                minimum,
                maximum,
                start,
                num,
            ),
        ))
        return self

    def execute(self):
        """Runs every queued read.

        Returns:
            list: One reply per read, in order.
        """
        replies = []
        for method, arguments in self.queued:
            replies.append(method(*arguments))
        self.queued = []
        return replies


class RefusingEngine:
    """A stand-in database engine that refuses every connection, so any fall-back to Postgres would show."""

    def connect(self):
        """Refuses to connect.

        Returns:
            None: This method never returns.

        Raises:
            RuntimeError: Always.
        """
        raise RuntimeError('this example has no database')


class CatalogueFiller:
    """Fills the Redis stand-in through the mapping cache's own encoders, as the daily warm would.

    Attributes:
        client (CatalogueRedis): The stand-in to fill.
        tier (MappingRedisTier): The tier whose key names and encoders are used.
        counts (dict): How many instruments each segment has.
    """

    def __init__(self, client):
        """Builds the filler and marks the mapping date as current.

        Args:
            client (CatalogueRedis): The stand-in to fill.

        Returns:
            None: This method returns nothing.
        """
        self.client = client
        self.tier = MappingRedisTier(MappingRedisConnection(client=client))
        self.counts = {}
        client.strings[self.tier.current_date_key()] = MAPPING_DATE.isoformat()

    def add(self, number, segment, shape, name, expiry_date=None, strike_price=None, option_type=None):
        """Adds one instrument's identity, catalogue member, name and handles.

        Args:
            number (int): The last digits of the instrument id.
            segment (str): The exchange-prefixed segment.
            shape (str): `security`, `future` or `option`.
            name (str): The symbol, or the underlying for a derivative.
            expiry_date (datetime.date | None): The expiry, for a derivative.
            strike_price (str | None): The strike, for an option.
            option_type (str | None): `CE` or `PE`, for an option.

        Returns:
            None: This method returns nothing.
        """
        identity = {
            'instrument_id': f'22222222-2222-5222-8222-{number:012d}',
            'exchange': 'nse',
            'segment': segment,
            'shape': shape,
            'symbol': None,
            'underlying_symbol': None,
            'expiry_date': expiry_date,
            'strike_price': None,
            'option_type': option_type,
            'mapping_date': MAPPING_DATE,
        }
        if shape == 'security':
            identity['symbol'] = name
        else:
            identity['underlying_symbol'] = name
        if strike_price is not None:
            identity['strike_price'] = decimal.Decimal(strike_price)
        identities = self.client.hashes.setdefault(self.tier.identity_key(MAPPING_DATE), {})
        identities[identity['instrument_id']] = self.tier.encode_identity(identity)
        members = self.client.sorted_sets.setdefault(self.tier.catalogue_key(MAPPING_DATE, segment), [])
        members.append(self.tier.encode_catalogue_member(identity))
        names = self.client.sorted_sets.setdefault(self.tier.names_key(MAPPING_DATE, segment), [])
        if name not in names:
            names.append(name)
        self.counts[segment] = self.counts.get(segment, 0) + 1

    def finish(self):
        """Writes the per-segment counts, which marks the day's catalogue as complete.

        Returns:
            None: This method returns nothing.
        """
        counts = {}
        for segment, count in self.counts.items():
            counts[segment] = str(count)
        self.client.hashes[self.tier.segments_key(MAPPING_DATE)] = counts


class BrowsingAndSearchingExample:
    """Builds a small catalogue and prints its segments, a listing and a search.

    Attributes:
        catalogue (InstrumentCatalogue): The catalogue being shown.
    """

    def __init__(self):
        """Fills the Redis stand-in and builds the catalogue over it.

        Returns:
            None: This method returns nothing.
        """
        client = CatalogueRedis()
        filler = CatalogueFiller(client)
        expiry = datetime.date(2026, 10, 27)
        filler.add(1, 'nse_equities', 'security', 'INFY')
        filler.add(2, 'nse_equities', 'security', 'RELIANCE')
        filler.add(3, 'nse_equity_index_futures', 'future', 'NIFTY', expiry)
        filler.add(4, 'nse_equity_index_options', 'option', 'NIFTY', expiry, '25000', 'PE')
        filler.add(5, 'nse_equity_index_options', 'option', 'NIFTY', expiry, '25000', 'CE')
        filler.add(6, 'nse_equity_index_options', 'option', 'BANKNIFTY', expiry, '55000', 'CE')
        filler.add(7, 'nse_equity_index_options', 'option', 'NIFTYNXT50', expiry, '70000', 'CE')
        filler.finish()
        mapping_cache = MappingCache(
            engine=RefusingEngine(),
            redis_connection=MappingRedisConnection(client=client),
        )
        self.catalogue = InstrumentCatalogue(mapping_cache)

    def describe(self, identity):
        """Writes one identity on one line.

        Args:
            identity (dict): The identity as the catalogue answers it.

        Returns:
            str: The description.
        """
        parts = [
            identity['segment'],
            identity['symbol'] or identity['underlying_symbol'],
        ]
        if identity['expiry_date'] is not None:
            parts.append(identity['expiry_date'])
        if identity['strike_price'] is not None:
            parts.append(str(identity['strike_price']))
        if identity['option_type'] is not None:
            parts.append(identity['option_type'])
        return ' '.join(parts)

    def run(self):
        """Prints the mapping date, the segments, the NSE listing and a search.

        Returns:
            None: This method returns nothing.
        """
        mapping_date, counts = self.catalogue.mapping_date()
        print(f'Mapping date {mapping_date}, counts from the cache: {counts}')
        segments = self.catalogue.segments()
        print(f'Exchanges: {segments["exchanges"]}')
        for segment in segments['segments']:
            print(f'  {segment["segment"]}: {segment["shape"]}, {segment["instruments"]} instruments, identified by {segment["identity_fields"]}')
        mapping_date, listing = self.catalogue.master('nse', 'all')
        print(f'Every NSE instrument on {mapping_date}:')
        for identity in listing:
            print(f'  {self.describe(identity)}')
        found = self.catalogue.search('nse', 'nse_equity_index_options', 'nifty', limit=10)
        print(f'Search for nifty on {found["mapping_date"]}:')
        for identity in found['instruments']:
            print(f'  {self.describe(identity)}')


if __name__ == '__main__':
    BrowsingAndSearchingExample().run()
