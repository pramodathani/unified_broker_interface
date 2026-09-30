"""Lists Fyers tickers with the kind and expiry the queue needs, reads what each ticker says, and sorts Fyers' refusals into the downloader's error kinds.

Fyers names an instrument's kind with a number that is not stable across segments, and its expiry is epoch seconds, which the queue's priority cannot read. `instruments` therefore reads the kind from the ticker's ending (`FUT` for a future, `CE` or `PE` for an option) and turns the expiry into a date. The program gives the downloader a stand-in database connection whose cursor answers with four tickers. `series_context`, a classmethod that needs no downloader, says the series is matched on the ticker as `order_symbol`, with the exchange and segments the ticker implies.

The second half fetches through a stand-in for `FyersAPI` that raises the `FyersAPIException` each of five refusals produces. An invalid symbol (-300) retires the series, code -16 means the session was refused, Cloudflare's error 1015 page is a block that must stop the broker, an ordinary 429 is a throttle, and -50, Fyers' catch-all input error, is left as it is, because it means this module asked for too wide a window rather than that the instrument is dead. The downloader is built without its constructor, as in `test_runs/candle_parse.py`, so nothing connects to PostgreSQL or logs in.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/fyers/FyersCandles/example_2_tickers_and_refusals.py
"""

import datetime

from stock_brokers.api.fyers import (
    FyersAPIException,
)
from stock_brokers.instruments.historical.base import (
    CandleError,
)
from stock_brokers.instruments.historical.fyers import (
    FyersCandles,
)


class TickerCursor:
    """A stand-in database cursor that answers the instrument master query with fixed rows.

    Attributes:
        rows (list): The rows `fetchall` returns.
    """

    def __init__(self, rows):
        """Holds the rows to answer with.

        Args:
            rows (list): Tuples of (ticker, expiry in epoch seconds as text).

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows

    def __enter__(self):
        """Enters the `with` block.

        Returns:
            TickerCursor: This cursor.
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


class TickerConnection:
    """A stand-in PostgreSQL connection over four rows of Fyers' instrument master.

    Attributes:
        rows (list): The rows every cursor answers with.
    """

    def __init__(self):
        """Builds the connection with four tickers.

        Returns:
            None: This method returns nothing.
        """
        self.rows = [
            (
                'NSE:RELIANCE-EQ',
                '0',
            ),
            (
                'NSE:NIFTY50-INDEX',
                '',
            ),
            (
                'NSE:RELIANCE26SEPFUT',
                '1790676000',
            ),
            (
                'NSE:NIFTY25D3026000CE',
                '1767088800',
            ),
        ]

    def cursor(self):
        """Opens a cursor.

        Returns:
            TickerCursor: A cursor over the rows.
        """
        return TickerCursor(self.rows)

    def commit(self):
        """Accepts a commit.

        Returns:
            None: This method returns nothing.
        """


class RefusingFyersAPI:
    """A stand-in for `FyersAPI` that refuses with a chosen Fyers error.

    Attributes:
        code (int): The code the refusal carries.
        message (str): The message the refusal carries.
    """

    def __init__(self, code, message):
        """Holds the refusal to raise.

        Args:
            code (int): Fyers' code, or the HTTP status for a page that is not Fyers' JSON.
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        self.code = code
        self.message = message

    def get(self, url, params=None):
        """Refuses a GET request.

        Args:
            url (str): The URL the downloader asked for.
            params (dict): The query parameters it sent.

        Returns:
            dict: Never returns.

        Raises:
            FyersAPIException: Always, carrying the chosen code and message.
        """
        raise FyersAPIException(code=self.code, message=self.message)


class TickersAndRefusalsExample:
    """Lists tickers, reads them, and classifies five refusals.

    Attributes:
        candles (FyersCandles): The downloader being shown.
    """

    def __init__(self):
        """Builds the downloader around the stand-in connection without running its constructor.

        Returns:
            None: This method returns nothing.
        """
        self.candles = object.__new__(FyersCandles)
        self.candles._connection = TickerConnection()

    def show_tickers(self):
        """Lists the instruments and reads each ticker.

        Returns:
            None: This method returns nothing.
        """
        for ticker, kind, expiry in self.candles.instruments():
            context = FyersCandles.series_context(ticker)
            print(f'{ticker}: kind {kind}, expiry {expiry}, matched on {context.match_on}, exchange {context.exchange}, {len(context.segments)} segments to search')

    def show_refusals(self):
        """Fetches through five refusing stand-ins and prints what each became.

        Returns:
            None: This method returns nothing.
        """
        refusals = [
            (
                -300,
                'Invalid symbol provided',
            ),
            (
                -16,
                'Could not authenticate the user',
            ),
            (
                429,
                'error code: 1015 - the owner of this website has banned you temporarily',
            ),
            (
                429,
                'request limit reached',
            ),
            (
                -50,
                'Date range cannot exceed 366 days for 1D, 1W and 1M',
            ),
        ]
        for code, message in refusals:
            self.candles._api = RefusingFyersAPI(code, message)
            try:
                self.candles.fetch_candles(
                    'NSE:RELIANCE-EQ',
                    'day',
                    datetime.date(2025, 1, 1),
                    datetime.date(2026, 9, 11),
                )
                outcome = 'answered'
            except CandleError as error:
                outcome = type(error).__name__
            except FyersAPIException as error:
                outcome = f'left as {type(error).__name__}'
            print(f'{code} "{message}": {outcome}')

    def run(self):
        """Runs both parts in turn.

        Returns:
            None: This method returns nothing.
        """
        self.show_tickers()
        self.show_refusals()


if __name__ == '__main__':
    TickersAndRefusalsExample().run()
