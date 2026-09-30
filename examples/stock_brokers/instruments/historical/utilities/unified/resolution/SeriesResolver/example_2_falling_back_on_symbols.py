"""Falls back on other brokers and on the trading symbol for series whose own token was never mapped, calling each step of `SeriesResolver` by hand.

Flattrade maps a share's EQ row and not its BE row, so its BE series have no mapping of their own. `SeriesResolver.fall_back` handles such a series in two steps. First, other brokers' mappings of the same exchange token vote, and an instrument backed by at least two brokers, and by more than any other, wins; `exchange_token_votes` gathers those votes in one query, rebuilding Zerodha's Kite token from the exchange token so its vote counts too. Failing that, the trading symbol is matched against the instrument master in the allowed segments, where a classified instrument outranks an uncategorised twin, several classified matches are ambiguous, and no match at all rejects the series.

This program calls `exchange_token_votes`, `fall_back`, `symbol_matches`, `instrument` and `resolution` directly, with contexts read by Flattrade's own `series_context`, so each step's answer is visible. The database behind the resolver is a stand-in engine holding a few mappings and instrument master rows, so no data store is reached; ORICONENT's temporary BE token 10163, filed as uncategorised by one broker, is the case the module's documentation describes. Notice that one broker's vote for the uncategorised twin is not enough to decide, so the symbol decides instead.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/utilities/unified/resolution/SeriesResolver/example_2_falling_back_on_symbols.py
"""

import datetime

from stock_brokers.instruments.historical.flattrade import (
    FlattradeCandles,
)
from stock_brokers.instruments.historical.utilities.unified.resolution import (
    SeriesResolver,
)


class VoteRow:
    """A stand-in for one result row of the exchange token vote query.

    Attributes:
        broker (str): The broker that maps the token.
        broker_token (str): Its token.
        instrument_id (str): The instrument it maps the token to.
    """

    def __init__(self, broker, broker_token, instrument_id):
        """Holds the row's columns.

        Args:
            broker (str): The broker that maps the token.
            broker_token (str): Its token.
            instrument_id (str): The instrument it maps the token to.

        Returns:
            None: This method returns nothing.
        """
        self.broker = broker
        self.broker_token = broker_token
        self.instrument_id = instrument_id


class InstrumentRow:
    """A stand-in for one result row of an instrument master query, read through `_mapping`.

    Attributes:
        instrument_id (str): The instrument's id.
        _mapping (dict): Every column by name, as SQLAlchemy rows offer them.
    """

    def __init__(self, columns):
        """Holds the row's columns.

        Args:
            columns (dict): Every column by name.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = columns['instrument_id']
        self._mapping = columns


class StandInResult:
    """A stand-in for a SQLAlchemy result.

    Attributes:
        rows (list): The rows.
    """

    def __init__(self, rows):
        """Holds the rows.

        Args:
            rows (list): The rows.

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows

    def all(self):
        """Every row.

        Returns:
            list: The rows.
        """
        return self.rows

    def one(self):
        """The only row.

        Returns:
            InstrumentRow: The row.
        """
        return self.rows[0]


class StandInConnection:
    """A stand-in for a SQLAlchemy connection over the stand-in mapped tables.

    Attributes:
        engine (StandInEngine): The engine holding the tables.
    """

    def __init__(self, engine):
        """Remembers the engine.

        Args:
            engine (StandInEngine): The engine holding the tables.

        Returns:
            None: This method returns nothing.
        """
        self.engine = engine

    def __enter__(self):
        """Opens the connection.

        Returns:
            StandInConnection: This connection.
        """
        return self

    def __exit__(self, exception_type, exception, traceback):
        """Closes the connection, letting any exception carry on.

        Args:
            exception_type (type | None): The class of an exception raised inside the block.
            exception (BaseException | None): The exception raised inside the block.
            traceback (types.TracebackType | None): Where it was raised.

        Returns:
            bool: Always False, so an exception is not swallowed.
        """
        return False

    def execute(self, statement, parameters):
        """Answers the exchange token vote query, the symbol query or the one-instrument query.

        Args:
            statement (sqlalchemy.TextClause): The SQL.
            parameters (dict): The bound parameters.

        Returns:
            StandInResult: The rows.
        """
        if 'GROUP BY' in str(statement):
            return StandInResult(self.engine.votes(parameters))
        if 'upper(m.symbol)' in str(statement):
            return StandInResult(self.engine.symbol_rows(parameters))
        instrument = self.engine.master[parameters['instrument_id']]
        rows = [
            InstrumentRow(instrument),
        ]
        return StandInResult(rows)


class StandInEngine:
    """A stand-in for the SQLAlchemy engine, holding other brokers' mappings and the instrument master.

    Attributes:
        mappings (list): (broker, broker_token, instrument_id, segment) rows of other brokers' mappings.
        master (dict): Instrument id to its row in the instrument master.
    """

    def __init__(self):
        """Fills in the mappings and the master rows.

        Returns:
            None: This method returns nothing.
        """
        self.mappings = []
        self.master = {}
        self.add_mapping('dhan', '7001', 'INDIAGLYCO')
        self.add_mapping('kotak', '7001', 'INDIAGLYCO')
        self.add_mapping('zerodha', str(7001 << 8 | 1), 'INDIAGLYCO')
        self.add_mapping('stoxkart', '10163', 'ORICONENT-UNCATEGORISED')
        self.add_instrument('INDIAGLYCO', 'INDIAGLYCO', 'nse_equities')
        self.add_instrument('ORICONENT', 'ORICONENT', 'nse_equities')
        self.add_instrument('ORICONENT-UNCATEGORISED', 'ORICONENT', 'nse_uncategorised')
        self.add_instrument('DUPL', 'DUPL', 'nse_equities')
        self.add_instrument('DUPL-ETF', 'DUPL', 'nse_exchange_traded_funds')

    def add_instrument(self, instrument_id, symbol, segment):
        """Adds one NSE instrument to the master.

        Args:
            instrument_id (str): The instrument's id, a readable name in this program.
            symbol (str): Its trading symbol.
            segment (str): Its segment.

        Returns:
            None: This method returns nothing.
        """
        self.master[instrument_id] = {
            'instrument_id': instrument_id,
            'exchange': 'nse',
            'segment': segment,
            'shape': 'security',
            'symbol': symbol,
            'first_mapping_date': datetime.date(2026, 8, 12),
            'last_mapping_date': datetime.date(2026, 9, 29),
        }

    def symbol_rows(self, parameters):
        """Selects the master rows the symbol query asks for.

        Args:
            parameters (dict): The query's bound parameters.

        Returns:
            list: One InstrumentRow per match.
        """
        rows = []
        for columns in self.master.values():
            if columns['exchange'] != parameters['exchange']:
                continue
            if columns['segment'] not in parameters['segments']:
                continue
            if columns['symbol'].upper() == parameters['symbol']:
                rows.append(InstrumentRow(columns))
        return rows

    def add_mapping(self, broker, broker_token, instrument_id):
        """Adds one other broker's mapping of an NSE share.

        Args:
            broker (str): The broker.
            broker_token (str): Its token.
            instrument_id (str): The instrument it maps to.

        Returns:
            None: This method returns nothing.
        """
        row = (
            broker,
            broker_token,
            instrument_id,
            'nse_equities',
        )
        self.mappings.append(row)

    def votes(self, parameters):
        """Selects the mappings the vote query asks for.

        Args:
            parameters (dict): The query's bound parameters.

        Returns:
            list: One VoteRow per matching (broker, token, instrument).
        """
        rows = []
        for broker, broker_token, instrument_id, segment in self.mappings:
            if segment not in parameters['segments']:
                continue
            voter = broker in parameters['voters'] and broker_token in parameters['exchange_tokens']
            zerodha = broker == 'zerodha' and parameters['include_zerodha'] and broker_token in parameters['zerodha_tokens']
            if voter or zerodha:
                rows.append(VoteRow(broker, broker_token, instrument_id))
        return rows

    def connect(self):
        """Opens a stand-in connection.

        Returns:
            StandInConnection: The connection.
        """
        return StandInConnection(self)


class StandInMappingResolver:
    """A stand-in for `MappingResolver` for series Flattrade never mapped.

    Attributes:
        engine (StandInEngine): The engine the series resolver queries directly.
    """

    def __init__(self):
        """Builds the engine.

        Returns:
            None: This method returns nothing.
        """
        self.engine = StandInEngine()

    def identity_spans(self, broker, broker_tokens, segments=None, match_on='broker_token'):
        """Answers that none of the tokens was ever mapped.

        Args:
            broker (str): The broker.
            broker_tokens (list): The tokens to look up.
            segments (tuple | None): The allowed segments, or None for any.
            match_on (str): The mapping column compared.

        Returns:
            dict: Always empty.
        """
        return {}


class FallingBackOnSymbolsExample:
    """Resolves series without mappings of their own, one step at a time.

    Attributes:
        resolver (SeriesResolver): The resolver being shown.
    """

    def __init__(self):
        """Builds the resolver over the stand-in mapping resolver.

        Returns:
            None: This method returns nothing.
        """
        self.resolver = SeriesResolver(StandInMappingResolver())

    def describe(self, resolution):
        """Prints one resolution on one line.

        Args:
            resolution (Resolution): The resolution.

        Returns:
            None: This method returns nothing.
        """
        print(f'  -> {resolution.instrument_id} {resolution.status} by {resolution.resolved_by}; {resolution.status_reason}')

    def fall_back(self, identifier):
        """Gathers the votes for one series and falls back on them and its symbol.

        Args:
            identifier (str): Flattrade's series identifier.

        Returns:
            None: This method returns nothing.
        """
        context = FlattradeCandles.series_context(identifier)
        contexts = [
            context,
        ]
        votes = self.resolver.exchange_token_votes('flattrade', contexts)
        print(f'{identifier}: votes {votes}')
        for resolution in self.resolver.fall_back(identifier, context, votes.get(context.exchange_token, {})):
            self.describe(resolution)

    def run(self):
        """Falls back for five series, then calls the look-ups directly.

        Returns:
            None: This method returns nothing.
        """
        self.fall_back('NSE|7001|INDIAGLYCO-BE')
        self.fall_back('NSE|10163|ORICONENT-BE')
        self.fall_back('NSE|20001|DUPL-BE')
        self.fall_back('NSE|30001|GONE-BE')
        self.fall_back('NFO|35003|NIFTY26SEPFUT')
        context = FlattradeCandles.series_context('NSE|10163|ORICONENT-BE')
        matches = self.resolver.symbol_matches('nse', context.segments, 'oriconent')
        for match in matches:
            print(f"symbol_matches ORICONENT: {match['instrument_id']} in {match['segment']}")
        instrument = self.resolver.instrument('INDIAGLYCO')
        print(f"instrument INDIAGLYCO: {instrument['segment']} seen {instrument['first_mapping_date']} to {instrument['last_mapping_date']}")
        resolution = self.resolver.resolution('NSE|7001|INDIAGLYCO-BE', instrument, 'manual', reason='set by hand')
        print(f'resolution built by hand: {resolution.instrument_id} {resolution.status} by {resolution.resolved_by}; {resolution.status_reason}')

if __name__ == '__main__':
    FallingBackOnSymbolsExample().run()
