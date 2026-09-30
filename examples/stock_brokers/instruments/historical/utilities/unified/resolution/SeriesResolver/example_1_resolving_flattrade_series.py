"""Resolves six of Flattrade's stored daily series to unified instruments, one for each rule the resolver applies.

A broker's price series is resolved once, as a whole: its bars reach back years before the first mapping date, so the question is which instruments its token has pointed at across the mapping dates there are, and which of them owns the series. `SeriesResolver.resolve` reads the identifier with the broker's own `series_context`, asks the mapping resolver for every instrument the token has been mapped to with the span of dates it was seen on, and chooses:

- one candidate settles it (RELIANCE);
- a candidate seen on fewer dates, entirely inside another's span, is a transient and is dropped (NIFTYBEES, filed as uncategorised for one day on 2026-08-12);
- between candidates seen side by side, the one other brokers map the same exchange token to wins, when at least two back it (ITADD over the stale ITETFADD row on token 17207);
- sequential candidates split the series in time at the boundary (MANBRO renamed KDGREEN on 2026-09-03);
- anything else is reported as ambiguous rather than guessed;
- a token the broker never mapped falls back on other brokers' mappings of its exchange token (INDIAGLYCO's BE series, backed by Dhan, Kotak and Zerodha, whose Kite token is rebuilt from the exchange token as 7001 shifted left eight bits plus NSE's segment code 1).

The mapping resolver and its database are replaced by small stand-ins holding those spans and other brokers' mappings, so no data store is reached; the stand-in engine answers the two queries `resolve` sends, and the names and dates follow the cases in the module's own documentation. The program finally calls `choose` by hand to show that a consensus of one broker is not enough.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/utilities/unified/resolution/SeriesResolver/example_1_resolving_flattrade_series.py
"""

import datetime

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
        """Answers the exchange token vote query or the one-instrument query.

        Args:
            statement (sqlalchemy.TextClause): The SQL.
            parameters (dict): The bound parameters.

        Returns:
            StandInResult: The rows.
        """
        if 'GROUP BY' in str(statement):
            return StandInResult(self.engine.votes(parameters))
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
        """Fills in the mappings and the master.

        Returns:
            None: This method returns nothing.
        """
        self.mappings = []
        self.master = {}
        self.add_mapping('dhan', '17207', 'ITADD')
        self.add_mapping('kotak', '17207', 'ITADD')
        self.add_mapping('groww', '17207', 'ITADD')
        self.add_mapping('stoxkart', '17207', 'ITADD')
        self.add_mapping('dhan', '7001', 'INDIAGLYCO')
        self.add_mapping('kotak', '7001', 'INDIAGLYCO')
        self.add_mapping('zerodha', str(7001 << 8 | 1), 'INDIAGLYCO')
        self.master['INDIAGLYCO'] = {
            'instrument_id': 'INDIAGLYCO',
            'exchange': 'nse',
            'segment': 'nse_equities',
            'shape': 'security',
            'symbol': 'INDIAGLYCO',
            'first_mapping_date': datetime.date(2026, 8, 12),
            'last_mapping_date': datetime.date(2026, 9, 29),
        }

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
    """A stand-in for `MappingResolver` that knows Flattrade's token spans.

    Attributes:
        engine (StandInEngine): The engine the series resolver queries directly.
        spans (dict): Flattrade token to the spans it has been mapped over.
    """

    def __init__(self):
        """Fills in the spans for five tokens.

        Returns:
            None: This method returns nothing.
        """
        self.engine = StandInEngine()
        self.spans = {}
        self.add_span('2885', 'RELIANCE', 'RELIANCE', 'nse_equities', '2026-08-12', '2026-09-29', 35)
        self.add_span('10576', 'NIFTYBEES', 'NIFTYBEES', 'nse_exchange_traded_funds', '2026-08-12', '2026-09-29', 35)
        self.add_span('10576', 'NIFTYBEES-UNCATEGORISED', 'NIFTYBEES', 'nse_uncategorised', '2026-08-12', '2026-08-12', 1)
        self.add_span('17207', 'ITETFADD', 'ITETFADD', 'nse_exchange_traded_funds', '2026-08-12', '2026-09-25', 32)
        self.add_span('17207', 'ITADD', 'ITADD', 'nse_exchange_traded_funds', '2026-08-14', '2026-09-29', 34)
        self.add_span('4617', 'MANBRO', 'MANBRO', 'nse_equities', '2026-08-12', '2026-09-02', 16)
        self.add_span('4617', 'KDGREEN', 'KDGREEN', 'nse_equities', '2026-09-03', '2026-09-29', 19)
        self.add_span('9999', 'TWINSA', 'TWINSA', 'nse_equities', '2026-08-12', '2026-09-25', 32)
        self.add_span('9999', 'TWINSB', 'TWINSB', 'nse_equities', '2026-08-14', '2026-09-29', 34)

    def add_span(self, token, instrument_id, symbol, segment, first_date, last_date, mapping_dates):
        """Adds one instrument a token has been mapped to, with its span.

        Args:
            token (str): Flattrade's token.
            instrument_id (str): The instrument's id, a readable name in this program.
            symbol (str): The instrument's symbol.
            segment (str): The instrument's segment.
            first_date (str): The first mapping date it was seen on.
            last_date (str): The last mapping date it was seen on.
            mapping_dates (int): How many mapping dates it was seen on.

        Returns:
            None: This method returns nothing.
        """
        span = {
            'instrument_id': instrument_id,
            'exchange': 'nse',
            'segment': segment,
            'shape': 'security',
            'symbol': symbol,
            'first_mapping_date': datetime.date.fromisoformat(first_date),
            'last_mapping_date': datetime.date.fromisoformat(last_date),
            'mapping_dates': mapping_dates,
        }
        self.spans.setdefault(token, []).append(span)

    def identity_spans(self, broker, broker_tokens, segments=None, match_on='broker_token'):
        """Answers every instrument each token has been mapped to, oldest first.

        Args:
            broker (str): The broker.
            broker_tokens (list): The tokens to look up.
            segments (tuple | None): The allowed segments, or None for any.
            match_on (str): The mapping column compared, which this stand-in ignores.

        Returns:
            dict: Token to a list of spans; tokens with none are absent.
        """
        found = {}
        for token in broker_tokens:
            for span in self.spans.get(token, []):
                if segments is None or span['segment'] in segments:
                    found.setdefault(token, []).append(span)
        return found


class ResolvingFlattradeSeriesExample:
    """Resolves six Flattrade series and prints each resolution.

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
        valid_from = resolution.valid_from.isoformat() if resolution.valid_from else None
        valid_to = resolution.valid_to.isoformat() if resolution.valid_to else None
        print(f'  -> {resolution.symbol} {resolution.status} by {resolution.resolved_by}, from {valid_from} to {valid_to}; {resolution.status_reason}')

    def run(self):
        """Resolves the series, then shows `choose` refusing a consensus of one.

        Returns:
            None: This method returns nothing.
        """
        identifiers = [
            'NSE|2885|RELIANCE-EQ',
            'NSE|10576|NIFTYBEES-EQ',
            'NSE|17207|ITETFADD-EQ',
            'NSE|4617|MANBRO-EQ',
            'NSE|9999|TWINS-EQ',
            'NSE|7001|INDIAGLYCO-BE',
        ]
        resolved = self.resolver.resolve('flattrade', identifiers)
        for identifier in identifiers:
            print(identifier)
            for resolution in resolved[identifier]:
                self.describe(resolution)
        spans = self.resolver.mapping_resolver.spans['9999']
        votes = {
            'TWINSA': 1,
        }
        print('choose between TWINSA and TWINSB with one broker behind TWINSA:')
        for resolution in self.resolver.choose('NSE|9999|TWINS-EQ', spans, votes):
            self.describe(resolution)


if __name__ == '__main__':
    ResolvingFlattradeSeriesExample().run()
