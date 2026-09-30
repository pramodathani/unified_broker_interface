"""Identifies holdings that arrive without a broker token, by ISIN and by ticker, and lists every instrument a stored token has pointed at.

A Groww holding carries only an ISIN and a trading symbol. `identity_by_isin` looks the ISIN up in the raw files of the seven brokers that publish one, takes each broker's own token from there, and resolves that token like any other. A dual-listed share has an NSE and a BSE identity, so the answer is a list, ordered here with NSE first because that is the preferred exchange; the same instrument found through a second broker is not repeated. `identity_by_symbol` searches the master table by ticker within given segments and never picks a winner. `identity_spans` lists, for a price series stored under a broker token, every instrument that token has meant over all mapping dates; asking it to match on a column other than `broker_token` or `order_symbol` raises `ValueError`.

The mapping cache and the engine are small stand-ins answering from rows in memory, so no Redis or PostgreSQL is needed. The rows are made up but use real identifiers: INFY's ISIN INE009A01021, Dhan's NSE token 1594 and BSE token 500209, and Fyers' token for NSE INFY.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/resolution/MappingResolver/example_2_holdings_without_a_token.py
"""

import datetime
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
    """A stand-in engine answering the ISIN, ticker and span queries from rows in memory.

    Attributes:
        raw_isin_rows (dict): Broker name to the rows its raw file gives for the ISIN query.
        symbol_rows (list): The rows the ticker query returns.
        span_rows (list): The rows the span query returns.
        brokers_searched (list): The raw files the ISIN look-up read, in order.
    """

    def __init__(self, raw_isin_rows, symbol_rows, span_rows):
        """Holds the rows.

        Args:
            raw_isin_rows (dict): Broker name to the rows its raw file gives for the ISIN query.
            symbol_rows (list): The rows the ticker query returns.
            span_rows (list): The rows the span query returns.

        Returns:
            None: This method returns nothing.
        """
        self.raw_isin_rows = raw_isin_rows
        self.symbol_rows = symbol_rows
        self.span_rows = span_rows
        self.brokers_searched = []

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

    def execute(self, statement, parameters):
        """Answers one query from the rows in memory.

        Args:
            statement (sqlalchemy.sql.elements.TextClause): The query.
            parameters (dict): The query's parameters.

        Returns:
            StandInResult: The answer.
        """
        sql = str(statement)
        if '.instruments WHERE download_date' in sql:
            broker = sql.split('FROM ')[1].split('.instruments')[0]
            self.brokers_searched.append(broker)
            return StandInResult(self.raw_isin_rows.get(broker, []))
        if 'first_mapping_date' in sql:
            return StandInResult(self.span_rows)
        return StandInResult(self.symbol_rows)


class StandInMappingCache:
    """A stand-in for `MappingCache` that knows today's mapping date and a few tokens' identities.

    Attributes:
        engine (StandInEngine): The engine the resolver borrows.
        current_date (datetime.date): The current mapping date.
        identities (dict): Broker name to a dict of token to identity.
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
        found = {}
        known = self.identities.get(broker, {})
        for broker_token in broker_tokens:
            if broker_token in known:
                found[broker_token] = known[broker_token]
        return found


class HoldingsWithoutATokenExample:
    """Resolves an ISIN and two tickers, and lists a token's spans.

    Attributes:
        engine (StandInEngine): The stand-in engine.
        resolver (MappingResolver): The resolver being shown.
        today (datetime.date): The current mapping date.
    """

    def __init__(self):
        """Builds the stand-ins and the resolver around them.

        Returns:
            None: This method returns nothing.
        """
        self.today = datetime.date(2026, 9, 28)
        nse_infy = self.identity('nse', 'INFY')
        bse_infy = self.identity('bse', 'INFY')
        nse_tcs = self.identity('nse', 'TCS')
        self.engine = StandInEngine(
            {
                'dhan': [
                    self.raw_row('1594'),
                    self.raw_row('500209'),
                ],
                'fyers': [
                    self.raw_row('10100000001594'),
                ],
            },
            [
                self.master_row(nse_infy),
                self.master_row(nse_tcs),
            ],
            [
                self.span_row(nse_infy, datetime.date(2025, 1, 2), self.today, 431),
            ],
        )
        mapping_cache = StandInMappingCache(
            self.engine,
            self.today,
            {
                'dhan': {
                    '1594': nse_infy,
                    '500209': bse_infy,
                },
                'fyers': {
                    '10100000001594': nse_infy,
                },
            },
        )
        self.resolver = MappingResolver(mapping_cache)

    def identity(self, exchange, symbol):
        """Builds the identity of one listed share on today's mapping.

        Args:
            exchange (str): The exchange, "nse" or "bse".
            symbol (str): The share's symbol.

        Returns:
            dict: The identity.
        """
        segment = f'{exchange}_equities'
        return {
            'instrument_id': instrument_id(
                exchange,
                segment,
                'security',
                {
                    'symbol': symbol,
                },
            ),
            'exchange': exchange,
            'segment': segment,
            'shape': 'security',
            'symbol': symbol,
            'underlying_symbol': None,
            'expiry_date': None,
            'strike_price': None,
            'option_type': None,
            'mapping_date': self.today,
        }

    def raw_row(self, broker_token):
        """Builds one raw-file row carrying INFY's ISIN.

        Args:
            broker_token (str): The broker's token in that row.

        Returns:
            types.SimpleNamespace: The row.
        """
        return types.SimpleNamespace(
            broker_token=broker_token,
            isin_code='INE009A01021',
        )

    def master_row(self, identity):
        """Builds one master-table row from an identity.

        Args:
            identity (dict): The identity.

        Returns:
            types.SimpleNamespace: The row.
        """
        return types.SimpleNamespace(
            instrument_id=identity['instrument_id'],
            exchange=identity['exchange'],
            segment=identity['segment'],
            shape=identity['shape'],
            symbol=identity['symbol'],
            underlying_symbol=None,
            expiry_date=None,
            strike_price=None,
            option_type=None,
        )

    def span_row(self, identity, first_mapping_date, last_mapping_date, mapping_dates):
        """Builds one span row for Flattrade's token 1594.

        Args:
            identity (dict): The instrument the token pointed at.
            first_mapping_date (datetime.date): The first date it did.
            last_mapping_date (datetime.date): The last date it did.
            mapping_dates (int): On how many mapping dates it did.

        Returns:
            types.SimpleNamespace: The row.
        """
        return types.SimpleNamespace(
            broker_token='1594',
            instrument_id=identity['instrument_id'],
            exchange=identity['exchange'],
            segment=identity['segment'],
            shape=identity['shape'],
            symbol=identity['symbol'],
            first_mapping_date=first_mapping_date,
            last_mapping_date=last_mapping_date,
            mapping_dates=mapping_dates,
        )

    def run(self):
        """Prints the ISIN answer, the ticker answer, the spans and the refused match column.

        Returns:
            None: This method returns nothing.
        """
        by_isin = self.resolver.identity_by_isin(
            [
                ' ine009a01021 ',
            ],
            self.today,
            preferred_exchange='nse',
        )
        print(f'Raw files searched: {self.engine.brokers_searched}')
        for found in by_isin['INE009A01021']:
            print(f'  INE009A01021 -> {found["exchange"]} {found["symbol"]}, found through {found["evidence_broker"]} token {found["evidence_token"]}')
        by_symbol = self.resolver.identity_by_symbol(
            'nse',
            [
                'nse_equities',
            ],
            [
                'infy',
                'tcs',
                'NOSUCHSHARE',
            ],
            self.today,
        )
        for symbol in by_symbol:
            print(f'Ticker {symbol}: {len(by_symbol[symbol])} match in {by_symbol[symbol][0]["segment"]}')
        spans = self.resolver.identity_spans(
            'flattrade',
            [
                1594,
            ],
            segments=[
                'nse_equities',
            ],
        )
        for span in spans['1594']:
            print(f'Flattrade 1594 meant {span["symbol"]} from {span["first_mapping_date"]} to {span["last_mapping_date"]} on {span["mapping_dates"]} dates')
        try:
            self.resolver.identity_spans(
                'flattrade',
                [
                    '1594',
                ],
                match_on='isin',
            )
        except ValueError as error:
            print(f'ValueError: {error}')


if __name__ == '__main__':
    HoldingsWithoutATokenExample().run()
