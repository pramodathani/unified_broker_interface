"""Finds every broker's token for INFY on today's mapping and on an earlier one, and turns a token back into an identity.

A `MappingResolver` is handed a mapping cache rather than building one, and takes its database engine from that cache. When the date asked about falls on the cache's current mapping date, the cache supplies the date and the identities, and only the broker rows are read from the database. An earlier date is answered from the database alone, using the latest mapping on or before it.

Both the cache and the engine here are small stand-ins. The cache says the current mapping date is 2026-09-28 and knows one Zerodha token. The engine answers the resolver's queries from rows held in memory: INFY was mapped at three brokers on 2026-09-28 and at two on 2026-08-14. Each stand-in counts what it is asked, so the output shows which answers came from the cache and which from the database. No Redis or PostgreSQL is needed.

Notice that asking about 2026-08-20 lands on the 2026-08-14 mapping, because nothing was mapped between those dates, and that the identity for today comes from the cache without a database query.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/resolution/MappingResolver/example_1_tokens_for_an_instrument.py
"""

import datetime
import decimal
import types

from stock_brokers.instruments.mapping.base import instrument_id
from stock_brokers.instruments.mapping.utilities.resolution import (
    MappingResolver,
)


class StandInResult:
    """A stand-in for a SQLAlchemy result holding fixed rows.

    Attributes:
        rows (list): The rows.
        value (object): The single value `scalar` returns.
    """

    def __init__(self, rows, value=None):
        """Holds the rows and the scalar value.

        Args:
            rows (list): The rows.
            value (object): The single value `scalar` returns.

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows
        self.value = value

    def all(self):
        """Every row.

        Returns:
            list: The rows.
        """
        return self.rows

    def one(self):
        """The only row.

        Returns:
            types.SimpleNamespace: The first row.
        """
        return self.rows[0]

    def scalar(self):
        """The single value of a one-column answer.

        Returns:
            object: The value.
        """
        return self.value


class StandInEngine:
    """A stand-in engine answering the resolver's queries about one instrument from rows in memory.

    Attributes:
        broker_rows (dict): Mapping date to the instrument's broker rows on that date.
        identity_rows (list): The rows a past-date identity query returns.
        queries (int): How many queries were run.
    """

    def __init__(self, broker_rows, identity_rows):
        """Holds the rows.

        Args:
            broker_rows (dict): Mapping date to the instrument's broker rows on that date.
            identity_rows (list): The rows a past-date identity query returns.

        Returns:
            None: This method returns nothing.
        """
        self.broker_rows = broker_rows
        self.identity_rows = identity_rows
        self.queries = 0

    def connect(self):
        """Opens a connection.

        Returns:
            StandInEngine: This engine, which also acts as its own connection.
        """
        return self

    def __enter__(self):
        """Enters the connection block.

        Returns:
            StandInEngine: This engine.
        """
        return self

    def __exit__(self, error_type, error, traceback):
        """Leaves the connection block.

        Args:
            error_type (type | None): The exception type raised inside the block, if any.
            error (BaseException | None): The exception raised inside the block, if any.
            traceback (types.TracebackType | None): The traceback, if any.

        Returns:
            bool: False, so an exception is never swallowed.
        """
        return False

    def latest_on_or_before(self, as_of_date):
        """The latest mapping date on or before a date.

        Args:
            as_of_date (datetime.date): The date asked about.

        Returns:
            datetime.date | None: The date, or None when nothing was mapped by then.
        """
        latest = None
        for mapping_date in self.broker_rows:
            if mapping_date <= as_of_date:
                if latest is None or mapping_date > latest:
                    latest = mapping_date
        return latest

    def execute(self, statement, parameters):
        """Answers one query from the rows in memory.

        Args:
            statement (sqlalchemy.sql.elements.TextClause): The query.
            parameters (dict): The query's parameters.

        Returns:
            StandInResult: The answer.
        """
        self.queries += 1
        sql = str(statement)
        if 'max(mapping_date) AS mapping_date' in sql:
            latest = self.latest_on_or_before(parameters['as_of_date'])
            return StandInResult([
                types.SimpleNamespace(
                    mapping_date=latest,
                ),
            ])
        if 'max(mapping_date)' in sql:
            return StandInResult([], self.latest_on_or_before(parameters['as_of_date']))
        if sql.startswith('SELECT broker, broker_token'):
            return StandInResult(self.broker_rows.get(parameters['mapping_date'], []))
        return StandInResult(self.identity_rows)


class StandInMappingCache:
    """A stand-in for `MappingCache` that knows today's mapping date and one token's identity.

    Attributes:
        engine (StandInEngine): The engine the resolver borrows.
        current_date (datetime.date): The current mapping date.
        identities (dict): Broker name to a dict of token to identity.
        lookups (int): How many identity look-ups were answered.
    """

    def __init__(self, engine, current_date, identities):
        """Holds the engine, the date and the identities.

        Args:
            engine (StandInEngine): The engine the resolver borrows.
            current_date (datetime.date): The current mapping date.
            identities (dict): Broker name to a dict of token to identity.

        Returns:
            None: This method returns nothing.
        """
        self.engine = engine
        self.current_date = current_date
        self.identities = identities
        self.lookups = 0

    def resolves_to_current_date(self, as_of_date):
        """The current mapping date when a request for this date lands on it.

        Args:
            as_of_date (datetime.date): The date asked about.

        Returns:
            datetime.date | None: The current mapping date, or None for an earlier date.
        """
        if as_of_date >= self.current_date:
            return self.current_date
        return None

    def identities_for_tokens(self, broker, broker_tokens, as_of_date, segments):
        """The identities of a broker's tokens on the current date.

        Args:
            broker (str): The broker name.
            broker_tokens (list): The tokens, as text.
            as_of_date (datetime.date): The date asked about.
            segments (list | None): The segments to restrict to, which this stand-in ignores.

        Returns:
            dict: Token to identity, for the tokens it knows.
        """
        self.lookups += 1
        found = {}
        known = self.identities.get(broker, {})
        for broker_token in broker_tokens:
            if broker_token in known:
                found[broker_token] = known[broker_token]
        return found


class TokensForAnInstrumentExample:
    """Looks INFY up on two dates and resolves a Zerodha token on two dates.

    Attributes:
        infy_id (str): INFY's instrument id on NSE.
        engine (StandInEngine): The stand-in engine.
        mapping_cache (StandInMappingCache): The stand-in cache.
        resolver (MappingResolver): The resolver being shown.
    """

    def __init__(self):
        """Builds the stand-ins and the resolver around them.

        Returns:
            None: This method returns nothing.
        """
        self.infy_id = instrument_id(
            'nse',
            'nse_equities',
            'security',
            {
                'symbol': 'INFY',
            },
        )
        today = datetime.date(2026, 9, 28)
        earlier = datetime.date(2026, 8, 14)
        self.engine = StandInEngine(
            {
                today: [
                    self.broker_row('dhan', '1594', 'INFY', None),
                    self.broker_row('fyers', '10100000001594', 'NSE:INFY-EQ', 'NSE:INFY-EQ'),
                    self.broker_row('zerodha', '408065', 'INFY', 'INFY'),
                ],
                earlier: [
                    self.broker_row('dhan', '1594', 'INFY', None),
                    self.broker_row('zerodha', '408065', 'INFY', 'INFY'),
                ],
            },
            [
                types.SimpleNamespace(
                    broker_token='408065',
                    mapping_date=earlier,
                    instrument_id=self.infy_id,
                    exchange='nse',
                    segment='nse_equities',
                    shape='security',
                    symbol='INFY',
                    underlying_symbol=None,
                    expiry_date=None,
                    strike_price=None,
                    option_type=None,
                ),
            ],
        )
        self.mapping_cache = StandInMappingCache(
            self.engine,
            today,
            {
                'zerodha': {
                    '408065': {
                        'instrument_id': self.infy_id,
                        'exchange': 'nse',
                        'segment': 'nse_equities',
                        'symbol': 'INFY',
                        'mapping_date': today,
                    },
                },
            },
        )
        self.resolver = MappingResolver(self.mapping_cache)

    def broker_row(self, broker, broker_token, broker_symbol, order_symbol):
        """Builds one broker mapping row with a lot of 1 and a tick of 0.05.

        Args:
            broker (str): The broker name.
            broker_token (str): The broker's token.
            broker_symbol (str): The broker's display symbol.
            order_symbol (str | None): The symbol an order is sent with, or None for a broker that orders by token.

        Returns:
            types.SimpleNamespace: The row.
        """
        return types.SimpleNamespace(
            broker=broker,
            broker_token=broker_token,
            broker_symbol=broker_symbol,
            order_symbol=order_symbol,
            lot_size=decimal.Decimal('1'),
            tick_size=decimal.Decimal('0.05'),
        )

    def print_tokens(self, label, as_of_date):
        """Looks INFY up for one date and prints the answer and the queries it cost.

        Args:
            label (str): What the look-up is.
            as_of_date (datetime.date): The date asked about.

        Returns:
            None: This method returns nothing.
        """
        queries_before = self.engine.queries
        mapping_date, rows = self.resolver.broker_tokens(
            'nse',
            'nse_equities',
            'security',
            {
                'symbol': 'INFY',
            },
            as_of_date,
        )
        print(f'{label}: mapping of {mapping_date}, {self.engine.queries - queries_before} database queries')
        for row in rows:
            print(f'  {row["broker"]}: token {row["broker_token"]}, order symbol {row["order_symbol"]}, lot {row["lot_size"]}, tick {row["tick_size"]}')

    def run(self):
        """Prints the mapping dates, the broker tokens and the identities.

        Returns:
            None: This method returns nothing.
        """
        print(f'INFY instrument id: {self.infy_id}')
        print(f'2026-09-30 resolves to {self.resolver.mapping_date_for(datetime.date(2026, 9, 30))}')
        print(f'2026-08-20 resolves to {self.resolver.mapping_date_for(datetime.date(2026, 8, 20))}')
        self.print_tokens('Today', datetime.date(2026, 9, 30))
        self.print_tokens('On 2026-08-20', datetime.date(2026, 8, 20))
        rows = self.resolver.broker_rows_on_date(self.infy_id, datetime.date(2026, 8, 14))
        print(f'Brokers mapped on 2026-08-14 exactly: {len(rows)}')
        queries_before = self.engine.queries
        today_identity = self.resolver.identity('zerodha', [408065], datetime.date(2026, 9, 30))
        print(f'Zerodha 408065 today: {today_identity["408065"]["symbol"]}, cache look-ups {self.mapping_cache.lookups}, database queries {self.engine.queries - queries_before}')
        earlier_identity = self.resolver.identity('zerodha', ['408065'], datetime.date(2026, 8, 20))
        print(f'Zerodha 408065 on 2026-08-20: {earlier_identity["408065"]["symbol"]} from the mapping of {earlier_identity["408065"]["mapping_date"]}')
        print(f'No tokens asked for: {self.resolver.identity("zerodha", [], datetime.date(2026, 9, 30))}')


if __name__ == '__main__':
    TokensForAnInstrumentExample().run()
