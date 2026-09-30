"""Builds Noren identifiers from an instrument master, reads what each says about its instrument, and shows how a Noren refusal object is read.

A Noren token is unique only within its exchange's scrip file, and the two endpoints need different fields, so `instruments` joins the exchange, the token and the trading symbol into one identifier and turns Noren's `27-OCT-2026` expiry into a date. `identifier_parts` splits it again, and `series_context`, a classmethod that needs no downloader, reads the exchange and segments. For NSE and BSE it also gives the exchange symbol with the series suffix removed, so `RELIANCE-EQ` becomes `RELIANCE`; an exchange name Noren's table does not know leaves everything but the token open.

A Noren refusal is a JSON object with `stat` and `emsg`, sent with HTTP 200. Its "no data" message is the same for an empty window and an unknown instrument, so `parse_response` reads it as no bars; only a throttle and an expired session raise, as `CandleThrottled` and `CandleAuthenticationError`, and the message names the broker.

The program uses `ShoonyaCandles`, the Noren subclass for Shoonya, so the instance has a broker name to report; everything shown is defined on `NorenCandles`. The downloader is built without its constructor, as in `test_runs/candle_parse.py`, and given a stand-in database connection whose cursor answers the instrument master query with four rows, so nothing connects to PostgreSQL or logs in.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/noren/NorenCandles/example_2_identifiers_and_refusal_objects.py
"""

from stock_brokers.instruments.historical.base import (
    CandleError,
)
from stock_brokers.instruments.historical.noren import (
    NorenCandles,
)
from stock_brokers.instruments.historical.shoonya import (
    ShoonyaCandles,
)


class ScripFileCursor:
    """A stand-in database cursor that answers the instrument master query with fixed rows.

    Attributes:
        rows (list): The rows `fetchall` returns.
    """

    def __init__(self, rows):
        """Holds the rows to answer with.

        Args:
            rows (list): Tuples of (exchange, token, trading symbol, instrument, expiry).

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows

    def __enter__(self):
        """Enters the `with` block.

        Returns:
            ScripFileCursor: This cursor.
        """
        return self

    def __exit__(self, exception_type, exception, traceback):
        """Leaves the `with` block without suppressing an exception.

        Args:
            exception_type (type | None): The exception's class, if one was raised.
            exception (BaseException | None): The exception, if one was raised.
            traceback (types.TracebackType | None): Its traceback, if one was raised.

        Returns:
            bool: Always False.
        """
        return False

    def execute(self, query):
        """Accepts the query without running it.

        Args:
            query (str): The SQL the downloader sent.

        Returns:
            None: This method returns nothing.
        """

    def fetchall(self):
        """Returns the fixed rows.

        Returns:
            list: The rows.
        """
        return self.rows


class ScripFileConnection:
    """A stand-in PostgreSQL connection over four rows of Noren scrip files.

    Attributes:
        rows (list): The rows every cursor answers with.
    """

    def __init__(self):
        """Builds the connection with four scrip file rows.

        Returns:
            None: This method returns nothing.
        """
        self.rows = [
            (
                'NSE',
                '2885',
                'RELIANCE-EQ',
                'EQ',
                None,
            ),
            (
                'NFO',
                '2885',
                'RELIANCE27OCT26F',
                'FUTSTK',
                '27-OCT-2026',
            ),
            (
                'MCX',
                '565899',
                'CRUDEOIL19OCT26',
                'FUTCOM',
                '19-OCT-2026',
            ),
            (
                'NSE',
                '26000',
                'Nifty 50',
                'INDEX',
                '',
            ),
        ]

    def cursor(self):
        """Opens a cursor.

        Returns:
            ScripFileCursor: A cursor over the rows.
        """
        return ScripFileCursor(self.rows)

    def commit(self):
        """Accepts a commit.

        Returns:
            None: This method returns nothing.
        """


class IdentifiersAndRefusalObjectsExample:
    """Lists identifiers, reads them, and parses three refusal objects.

    Attributes:
        candles (ShoonyaCandles): The downloader being shown.
    """

    def __init__(self):
        """Builds the downloader around the stand-in connection without running its constructor.

        Returns:
            None: This method returns nothing.
        """
        self.candles = object.__new__(ShoonyaCandles)
        self.candles._connection = ScripFileConnection()

    def show_identifiers(self):
        """Lists the instruments and reads each identifier, then one with an unknown exchange.

        Returns:
            None: This method returns nothing.
        """
        identifiers = []
        for identifier, instrument_type, expiry in self.candles.instruments():
            print(f'{identifier}: {instrument_type}, expiry {expiry}')
            identifiers.append(identifier)
        identifiers.append('XYZ|123|UNKNOWN')
        for identifier in identifiers:
            exchange_name, token, trading_symbol = self.candles.identifier_parts(identifier)
            context = NorenCandles.series_context(identifier)
            if context.segments:
                segments = f'{len(context.segments)} segments'
            else:
                segments = 'any segment'
            print(f'  {exchange_name} {token} {trading_symbol}: exchange {context.exchange}, {segments}, symbol {context.symbol}')

    def show_refusals(self):
        """Parses three refusal objects and prints what each became.

        Returns:
            None: This method returns nothing.
        """
        messages = [
            'Error Occurred : 5 "no data"',
            'Rate_Limited: too many requests',
            'Session Expired :  Invalid Session Key',
        ]
        for message in messages:
            refusal = {
                'stat': 'Not_Ok',
                'emsg': message,
            }
            try:
                bars = self.candles.parse_response(refusal, '1minute')
                outcome = f'{len(bars)} bars'
            except CandleError as error:
                outcome = f'{type(error).__name__}: {error}'
            print(f'"{message}": {outcome}')

    def run(self):
        """Runs both parts in turn.

        Returns:
            None: This method returns nothing.
        """
        self.show_identifiers()
        self.show_refusals()


if __name__ == '__main__':
    IdentifiersAndRefusalObjectsExample().run()
