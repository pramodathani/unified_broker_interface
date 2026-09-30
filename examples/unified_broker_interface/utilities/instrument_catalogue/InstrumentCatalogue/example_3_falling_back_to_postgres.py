"""Shows when an `InstrumentCatalogue` has to read Postgres instead of Redis, and the errors it answers when nothing was mapped.

The catalogue answers from the Redis tier of the mapping cache whenever it can, and reads the unified instrument tables only in three cases: a date before the current mapping date, a cold cache whose day's catalogue was never warmed, and history of an instrument no longer mapped. Each time it does, it logs a line saying so. When nothing has been mapped at all it raises `RequestError` with 503, and when nothing had been mapped by a past date it raises one with 404.

This program builds a real `MappingCache` around a Redis stand-in and a scripted database stand-in. The database stand-in answers each query in turn from a list of scripted replies and records the start of every statement, so the output shows which queries the catalogue sent without any database. A logging handler prints the catalogue's own log lines to the output, without timestamps.

Notice that the first case asks Postgres for the latest mapping date because Redis holds none, that the past-date search is answered from the instrument table on the 2026-08-31 mapping date, and that the cold cache logs a warning before counting segments in Postgres.

Run it from the project root:

    python examples/unified_broker_interface/utilities/instrument_catalogue/InstrumentCatalogue/example_3_falling_back_to_postgres.py
"""

import datetime
import logging
import sys

from stock_brokers.instruments.mapping.utilities.cache import (
    MappingCache,
    MappingRedisConnection,
    MappingRedisTier,
)
from unified_broker_interface.utilities.instrument_catalogue import (
    InstrumentCatalogue,
)
from unified_broker_interface.utilities.instrument_identity import (
    RequestError,
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


class ScriptedRow:
    """A stand-in database row, readable by attribute and through `_mapping`.

    Attributes:
        _mapping (dict): The row's columns by name.
    """

    def __init__(self, columns):
        """Builds the row.

        Args:
            columns (dict): The row's columns by name.

        Returns:
            None: This method returns nothing.
        """
        self._mapping = columns
        for name, value in columns.items():
            setattr(self, name, value)


class ScriptedResult:
    """A stand-in query result holding one scripted reply.

    Attributes:
        reply (object): A single value for `scalar`, or a list of rows for `all`.
    """

    def __init__(self, reply):
        """Builds the result.

        Args:
            reply (object): The scripted reply.

        Returns:
            None: This method returns nothing.
        """
        self.reply = reply

    def scalar(self):
        """The single value.

        Returns:
            object: The scripted value.
        """
        return self.reply

    def all(self):
        """Every row.

        Returns:
            list: The scripted rows.
        """
        return self.reply


class ScriptedConnection:
    """A stand-in database connection that answers each query with the engine's next scripted reply.

    Attributes:
        engine (ScriptedEngine): The engine holding the replies.
    """

    def __init__(self, engine):
        """Builds the connection.

        Args:
            engine (ScriptedEngine): The engine holding the replies.

        Returns:
            None: This method returns nothing.
        """
        self.engine = engine

    def __enter__(self):
        """Opens the connection.

        Returns:
            ScriptedConnection: This connection.
        """
        return self

    def __exit__(self, exception_type, exception, traceback):
        """Closes the connection.

        Args:
            exception_type (type | None): The exception's type, if one was raised.
            exception (BaseException | None): The exception, if one was raised.
            traceback (object | None): Its traceback.

        Returns:
            bool: False, so an exception is not swallowed.
        """
        del exception_type
        del exception
        del traceback
        return False

    def execute(self, statement, parameters=None):
        """Records the statement's first words and answers the next scripted reply.

        Args:
            statement (sqlalchemy.sql.elements.TextClause): The statement.
            parameters (dict | None): Its parameters.

        Returns:
            ScriptedResult: The result.
        """
        del parameters
        words = str(statement).split()
        print(f'  Postgres query: {" ".join(words[:4])} ...')
        return ScriptedResult(self.engine.replies.pop(0))


class ScriptedEngine:
    """A stand-in database engine whose connections answer scripted replies in turn.

    Attributes:
        replies (list): The replies still to give, in order.
    """

    def __init__(self, replies):
        """Builds the engine.

        Args:
            replies (list): The replies to give, in order.

        Returns:
            None: This method returns nothing.
        """
        self.replies = replies

    def connect(self):
        """Opens a connection.

        Returns:
            ScriptedConnection: The connection.
        """
        return ScriptedConnection(self)


class FallingBackToPostgresExample:
    """Runs four requests that the Redis tier cannot answer on its own."""

    def build(self, current_date, warmed, replies):
        """Builds a catalogue over a Redis stand-in and a scripted database.

        Args:
            current_date (datetime.date | None): The mapping date Redis holds, or None for none.
            warmed (bool): Whether the day's catalogue was warmed into Redis.
            replies (list): The database's scripted replies, in order.

        Returns:
            InstrumentCatalogue: The catalogue.
        """
        client = CatalogueRedis()
        tier = MappingRedisTier(MappingRedisConnection(client=client))
        if current_date is not None:
            client.strings[tier.current_date_key()] = current_date.isoformat()
        if warmed:
            client.hashes[tier.segments_key(current_date)] = {
                'nse_equities': '2',
            }
        mapping_cache = MappingCache(
            engine=ScriptedEngine(replies),
            redis_connection=MappingRedisConnection(client=client),
        )
        return InstrumentCatalogue(mapping_cache)

    def nothing_mapped(self):
        """Asks for the mapping date when neither Redis nor Postgres has one.

        Returns:
            None: This method returns nothing.
        """
        print('Nothing mapped anywhere:')
        catalogue = self.build(None, False, [
            None,
        ])
        try:
            catalogue.mapping_date()
        except RequestError as error:
            print(f'  {error.status} {error.message}')

    def past_date_search(self):
        """Searches as of a date before the current mapping date.

        Returns:
            None: This method returns nothing.
        """
        print('Search as of 2026-09-01:')
        row = ScriptedRow({
            'instrument_id': '22222222-2222-5222-8222-000000000001',
            'exchange': 'nse',
            'segment': 'nse_equities',
            'shape': 'security',
            'symbol': 'INFY',
            'underlying_symbol': None,
            'expiry_date': None,
            'strike_price': None,
            'option_type': None,
        })
        catalogue = self.build(MAPPING_DATE, True, [
            datetime.date(2026, 8, 31),
            [
                row,
            ],
        ])
        found = catalogue.search('nse', 'nse_equities', 'inf', as_of=datetime.date(2026, 9, 1))
        for identity in found['instruments']:
            print(f'  found {identity["symbol"]} on mapping date {found["mapping_date"]}')

    def before_anything_mapped(self):
        """Asks for a listing as of a date before anything was mapped.

        Returns:
            None: This method returns nothing.
        """
        print('Listing as of 2020-01-01:')
        catalogue = self.build(MAPPING_DATE, True, [
            None,
        ])
        try:
            catalogue.master('nse', 'all', as_of=datetime.date(2020, 1, 1))
        except RequestError as error:
            print(f'  {error.status} {error.message}')

    def cold_cache(self):
        """Lists the segments when the day's catalogue was never warmed into Redis.

        Returns:
            None: This method returns nothing.
        """
        print('Cold cache:')
        counted = [
            ScriptedRow({
                'segment': 'nse_equities',
                'instruments': 2412,
            }),
            ScriptedRow({
                'segment': 'nse_equity_index_futures',
                'instruments': 12,
            }),
        ]
        catalogue = self.build(MAPPING_DATE, False, [
            counted,
        ])
        segments = catalogue.segments()
        for segment in segments['segments']:
            print(f'  {segment["segment"]}: {segment["instruments"]} instruments')

    def run(self):
        """Prints the catalogue's log lines and runs the four requests.

        Returns:
            None: This method returns nothing.
        """
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('  log %(levelname)s: %(message)s'))
        catalogue_logger = logging.getLogger('rest_api.instruments')
        catalogue_logger.addHandler(handler)
        catalogue_logger.setLevel(logging.INFO)
        self.nothing_mapped()
        self.past_date_search()
        self.before_anything_mapped()
        self.cold_cache()


if __name__ == '__main__':
    FallingBackToPostgresExample().run()
