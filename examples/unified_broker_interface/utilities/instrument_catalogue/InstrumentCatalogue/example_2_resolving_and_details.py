"""Resolves instruments named in requests and answers their details and additional details, one at a time and as a list.

The `/details` and `/additional_details` routes name an instrument by id or by its identity fields. An `InstrumentCatalogue` resolves each name to an identity from the mapping cache's Redis tier, then reads the instrument's first and last seen dates, the instrument it is written on, every broker's order handle and every broker's extra attributes. A list of instruments costs the same Redis round trips as one, and an instrument the cache does not hold gets its own 404 `RequestError` in the list while the others are still answered.

This program builds a real `MappingCache` around a Redis stand-in, filled through the tier's own encoders exactly as the daily warm lays the keys out, and a database stand-in that refuses every connection, so nothing falls back to Postgres. The catalogue holds INFY, carried by Zerodha and Dhan, and a NIFTY future and option carried by Zerodha and Dhan with the option resolved to the future as its underlying.

Notice that the lot size of the option is 75 while INFY's is 1, that the tick size is the value the brokers agree on and is null when two brokers disagree one to one, that the unknown symbol in the list becomes a 404 entry in its place, and that the additional details give every broker the full list of attribute names with null where it publishes nothing.

Run it from the project root:

    python examples/unified_broker_interface/utilities/instrument_catalogue/InstrumentCatalogue/example_2_resolving_and_details.py
"""

import datetime
import decimal

from stock_brokers.instruments.mapping.utilities.cache import (
    MappingCache,
    MappingRedisConnection,
    MappingRedisTier,
)
from unified_broker_interface.utilities import instrument_identity
from unified_broker_interface.utilities.instrument_catalogue import (
    InstrumentCatalogue,
)
from unified_broker_interface.utilities.instrument_identity import (
    RequestError,
)

MAPPING_DATE = datetime.date(2026, 9, 30)
INFY_ID = '22222222-2222-5222-8222-000000000001'
FUTURE_ID = '22222222-2222-5222-8222-000000000003'
OPTION_ID = '22222222-2222-5222-8222-000000000005'


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


class DetailsFiller:
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

    def add(self, identity, handles, attributes):
        """Adds one instrument's identity, catalogue member, seen dates, handles and attributes.

        Args:
            identity (dict): The instrument's identity fields.
            handles (dict): Each broker's order handle.
            attributes (dict): Each broker's published extra attributes.

        Returns:
            None: This method returns nothing.
        """
        full_identity = {
            'instrument_id': None,
            'exchange': 'nse',
            'segment': None,
            'shape': None,
            'symbol': None,
            'underlying_symbol': None,
            'expiry_date': None,
            'strike_price': None,
            'option_type': None,
            'mapping_date': MAPPING_DATE,
        }
        full_identity.update(identity)
        instrument_id = full_identity['instrument_id']
        segment = full_identity['segment']
        identities = self.client.hashes.setdefault(self.tier.identity_key(MAPPING_DATE), {})
        identities[instrument_id] = self.tier.encode_identity(full_identity)
        members = self.client.sorted_sets.setdefault(self.tier.catalogue_key(MAPPING_DATE, segment), [])
        members.append(self.tier.encode_catalogue_member(full_identity))
        seen = self.client.hashes.setdefault(self.tier.seen_key(MAPPING_DATE), {})
        seen[instrument_id] = self.tier.encode_seen(datetime.date(2024, 1, 2), MAPPING_DATE)
        stored_handles = self.client.hashes.setdefault(self.tier.order_handles_key(MAPPING_DATE), {})
        stored_handles[instrument_id] = self.tier.encode_order_handles(handles)
        stored_attributes = self.client.hashes.setdefault(self.tier.additional_attributes_key(MAPPING_DATE), {})
        stored_attributes[instrument_id] = self.tier.encode_additional_attributes(attributes)
        self.counts[segment] = self.counts.get(segment, 0) + 1

    def set_underlying(self, instrument_id, underlying_id):
        """Records which instrument a derivative is written on.

        Args:
            instrument_id (str): The derivative's id.
            underlying_id (str): The id of what it is written on.

        Returns:
            None: This method returns nothing.
        """
        underlyings = self.client.hashes.setdefault(self.tier.underlyings_key(MAPPING_DATE), {})
        underlyings[instrument_id] = underlying_id

    def finish(self):
        """Writes the per-segment counts, which marks the day's catalogue as complete.

        Returns:
            None: This method returns nothing.
        """
        counts = {}
        for segment, count in self.counts.items():
            counts[segment] = str(count)
        self.client.hashes[self.tier.segments_key(MAPPING_DATE)] = counts


class ResolvingAndDetailsExample:
    """Builds a three-instrument catalogue and prints resolutions, details and additional details.

    Attributes:
        catalogue (InstrumentCatalogue): The catalogue being shown.
    """

    def __init__(self):
        """Fills the Redis stand-in and builds the catalogue over it.

        Returns:
            None: This method returns nothing.
        """
        client = CatalogueRedis()
        filler = DetailsFiller(client)
        expiry = datetime.date(2026, 10, 27)
        filler.add(
            {
                'instrument_id': INFY_ID,
                'segment': 'nse_equities',
                'shape': 'security',
                'symbol': 'INFY',
            },
            {
                'dhan': self.handle('1594', 'INFY', '1', '0.10'),
                'zerodha': self.handle('408065', 'INFY', '1', '0.05'),
            },
            {
                'dhan': {
                    'isin': 'INE009A01021',
                    'series': 'EQ',
                },
                'zerodha': {
                    'isin': 'INE009A01021',
                    'display_name': 'INFOSYS',
                },
            },
        )
        filler.add(
            {
                'instrument_id': FUTURE_ID,
                'segment': 'nse_equity_index_futures',
                'shape': 'future',
                'underlying_symbol': 'NIFTY',
                'expiry_date': expiry,
            },
            {
                'zerodha': self.handle('35001', 'NIFTY26OCTFUT', '75', '0.10'),
            },
            {},
        )
        filler.add(
            {
                'instrument_id': OPTION_ID,
                'segment': 'nse_equity_index_options',
                'shape': 'option',
                'underlying_symbol': 'NIFTY',
                'expiry_date': expiry,
                'strike_price': decimal.Decimal('25000'),
                'option_type': 'CE',
            },
            {
                'dhan': self.handle('41234', 'NIFTY-Oct2026-25000-CE', '75', '0.05'),
                'zerodha': self.handle('12345678', 'NIFTY26O2725000CE', '75', '0.05'),
            },
            {},
        )
        filler.set_underlying(OPTION_ID, FUTURE_ID)
        filler.finish()
        mapping_cache = MappingCache(
            engine=RefusingEngine(),
            redis_connection=MappingRedisConnection(client=client),
        )
        self.catalogue = InstrumentCatalogue(mapping_cache)

    @staticmethod
    def handle(broker_token, order_symbol, lot_size, tick_size):
        """Builds one broker's order handle.

        Args:
            broker_token (str): The broker's token for the instrument.
            order_symbol (str): The symbol the broker's order API takes.
            lot_size (str): The broker's lot size.
            tick_size (str): The broker's tick size in rupees.

        Returns:
            dict: The handle.
        """
        return {
            'broker_token': broker_token,
            'order_symbol': order_symbol,
            'lot_size': lot_size,
            'tick_size': tick_size,
        }

    def print_details(self, details):
        """Prints the parts of one details answer that differ between instruments.

        Args:
            details (dict): The details answer.

        Returns:
            None: This method returns nothing.
        """
        brokers = []
        for handle in details['carried_by']:
            brokers.append(f'{handle["broker"]} {handle["broker_token"]}')
        print(f'  {details["segment"]} {details["symbol"] or details["underlying_symbol"]}: lot {details["lot_size"]}, tick {details["tick_size"]}, seen {details["first_seen_date"]} to {details["last_seen_date"]}')
        print(f'    underlying {details["underlying_instrument_id"]}; carried by {", ".join(brokers)}')

    def run(self):
        """Resolves, then answers details and additional details one at a time and as a list.

        Returns:
            None: This method returns nothing.
        """
        infy = instrument_identity.parse_instrument({
            'exchange': 'nse',
            'segment': 'equities',
            'symbol': 'infy',
        })
        option = instrument_identity.parse_instrument({
            'exchange': 'nse',
            'segment': 'equity_index_options',
            'underlying_symbol': 'NIFTY',
            'expiry_date': '2026-10-27',
            'strike_price': '25000',
            'option_type': 'CE',
        })
        future = instrument_identity.parse_instrument({
            'instrument_id': FUTURE_ID,
        })
        unknown = instrument_identity.parse_instrument({
            'exchange': 'nse',
            'segment': 'equities',
            'symbol': 'NOSUCHCO',
        })
        identity, mapping_date, cached = self.catalogue.resolve(option)
        print(f'resolve: {identity["instrument_id"]} on {mapping_date}, from the cache {cached}')
        queries = [
            infy,
            unknown,
            future,
        ]
        mapping_date, resolutions = self.catalogue.resolve_many(queries)
        for resolution in resolutions:
            if isinstance(resolution, RequestError):
                print(f'resolve_many: {resolution.status} {resolution.message}')
            else:
                print(f'resolve_many: {resolution[0]["instrument_id"]}, from the cache {resolution[1]}')
        print('details of the option:')
        self.print_details(self.catalogue.details(option))
        print('details_many:')
        for answer in self.catalogue.details_many(queries):
            if isinstance(answer, RequestError):
                print(f'  {answer.status} {answer.message}')
            else:
                self.print_details(answer)
        additional = self.catalogue.additional_details(infy)
        print(f'additional_details of INFY: {len(additional["attribute_names"])} attribute names')
        for entry in additional['carried_by']:
            print(f'  {entry["broker"]}: isin {entry["isin"]}, series {entry["series"]}, display_name {entry["display_name"]}')
        answers = self.catalogue.additional_details_many(queries)
        for answer in answers:
            if isinstance(answer, RequestError):
                print(f'additional_details_many: {answer.status}')
            else:
                print(f'additional_details_many: {answer["instrument_id"]} with {len(answer["carried_by"])} brokers')
        handles = [
            self.handle('1', 'A', '1', '0.05'),
            self.handle('2', 'B', '1', '0.05'),
            self.handle('3', 'C', '1', '0.10'),
        ]
        print(f'agreed_tick_size of 0.05, 0.05, 0.10: {self.catalogue.agreed_tick_size(handles)}')


if __name__ == '__main__':
    ResolvingAndDetailsExample().run()
