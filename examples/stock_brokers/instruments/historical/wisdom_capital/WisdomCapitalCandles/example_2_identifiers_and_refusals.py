"""Builds Wisdom Capital identifiers from its instrument master, reads what each says about its instrument, and classifies the platform's refusals.

One XTS instrument id appears under several segments, so `instruments` joins the segment's number to the instrument id, as in `1|2885`, and turns XTS's numeric instrument type into a word the queue's priority understands (`8` is cash, `1` a future). Rows in a segment the platform has no number for are left out. The program gives the downloader a stand-in database connection whose cursor answers with four rows, one of them in a segment the table does not know. `identifier_parts` splits an identifier again, and `series_context`, a classmethod that needs no downloader, reads the exchange and segments its number names.

The platform raises its conditions with codes of its own. The program fetches through a stand-in for `WisdomCapitalAPI` that raises the `WisdomCapitalAPIException` for each of three: `e-apirl` is a rate limit, `e-session` a dead session and `e-instrument` an instrument the platform will not serve, which retires the series. The stand-in also hands out the market data token that `after_relogin` takes before any request is made.

A `WisdomCapitalCandles` constructor opens a PostgreSQL connection and logs in, so the program builds the object without running its constructor, as `test_runs/candle_parse.py` does.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/wisdom_capital/WisdomCapitalCandles/example_2_identifiers_and_refusals.py
"""

import datetime

from stock_brokers.api.wisdom_capital import (
    WisdomCapitalAPIException,
)
from stock_brokers.instruments.historical.base import (
    CandleError,
)
from stock_brokers.instruments.historical.wisdom_capital import (
    WisdomCapitalCandles,
)


class InstrumentMasterCursor:
    """A stand-in database cursor that answers the instrument master query with fixed rows.

    Attributes:
        rows (list): The rows `fetchall` returns.
    """

    def __init__(self, rows):
        """Holds the rows to answer with.

        Args:
            rows (list): Tuples of (segment name, instrument id, instrument type, expiry).

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows

    def __enter__(self):
        """Enters the `with` block.

        Returns:
            InstrumentMasterCursor: This cursor.
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


class InstrumentMasterConnection:
    """A stand-in PostgreSQL connection over four rows of the XTS instrument master.

    Attributes:
        rows (list): The rows every cursor answers with.
    """

    def __init__(self):
        """Builds the connection with four instrument master rows.

        Returns:
            None: This method returns nothing.
        """
        self.rows = [
            (
                'NSECM',
                '2885',
                8,
                None,
            ),
            (
                'BSECM',
                '500325',
                8,
                None,
            ),
            (
                'MCXFO',
                '565899',
                1,
                '2026-10-19T23:59:59',
            ),
            (
                'NSEXX',
                '777',
                8,
                None,
            ),
        ]

    def cursor(self):
        """Opens a cursor.

        Returns:
            InstrumentMasterCursor: A cursor over the rows.
        """
        return InstrumentMasterCursor(self.rows)

    def commit(self):
        """Accepts a commit.

        Returns:
            None: This method returns nothing.
        """


class RefusingWisdomCapitalAPI:
    """A stand-in for `WisdomCapitalAPI` that hands out a market data token and refuses every chart request.

    Attributes:
        code (str | None): The platform code the next refusal carries.
        message (str | None): The message the next refusal carries.
    """

    def __init__(self):
        """Builds the stand-in with no refusal chosen yet.

        Returns:
            None: This method returns nothing.
        """
        self.code = None
        self.message = None

    def replace_market_data_session(self, stale_access_token=None):
        """Hands out the market data session in force.

        Args:
            stale_access_token (str | None): A token that was refused, or None when none was.

        Returns:
            dict: The session's `access_token` and `user_id`.
        """
        return {
            'access_token': 'market-data-token-1',
            'user_id': 'WC1001',
        }

    def get(self, url, headers=None, params=None):
        """Refuses a GET request with the chosen code.

        Args:
            url (str): The URL the downloader asked for.
            headers (dict): The headers it sent.
            params (dict): The query parameters it sent.

        Returns:
            dict: Never returns.

        Raises:
            WisdomCapitalAPIException: Always, carrying the chosen code and message.
        """
        raise WisdomCapitalAPIException(code=self.code, message=self.message)


class IdentifiersAndRefusalsExample:
    """Lists identifiers, reads them, and classifies three refusals.

    Attributes:
        api (RefusingWisdomCapitalAPI): The stand-in Wisdom Capital API.
        candles (WisdomCapitalCandles): The downloader being shown.
    """

    def __init__(self):
        """Builds the downloader around the stand-ins without running its constructor.

        Returns:
            None: This method returns nothing.
        """
        self.api = RefusingWisdomCapitalAPI()
        self.candles = object.__new__(WisdomCapitalCandles)
        self.candles._connection = InstrumentMasterConnection()
        self.candles._api = self.api
        self.candles._empty_streak = 0

    def show_identifiers(self):
        """Lists the instruments and reads each identifier.

        Returns:
            None: This method returns nothing.
        """
        instruments = self.candles.instruments()
        print(f'Instruments to download: {len(instruments)} of 4 rows')
        for identifier, instrument_type, expiry in instruments:
            segment_number, instrument_identifier = self.candles.identifier_parts(identifier)
            context = WisdomCapitalCandles.series_context(identifier)
            print(f'{identifier}: segment {segment_number}, instrument {instrument_identifier}, {instrument_type}, expiry {expiry}, exchange {context.exchange}, {len(context.segments)} segments to search')

    def show_refusals(self):
        """Fetches through three refusals and prints what each became.

        Returns:
            None: This method returns nothing.
        """
        self.candles.after_relogin()
        refusals = [
            (
                'e-apirl-0004',
                'Rate limit exceeded',
            ),
            (
                'e-session-0002',
                'Invalid Token',
            ),
            (
                'e-instrument-0001',
                'Instrument not found',
            ),
        ]
        for code, message in refusals:
            self.api.code = code
            self.api.message = message
            try:
                self.candles.fetch_candles(
                    '2|35001',
                    '5minute',
                    datetime.date(2025, 1, 1),
                    datetime.date(2025, 3, 31),
                )
                outcome = 'answered'
            except CandleError as error:
                outcome = type(error).__name__
            print(f'{code} "{message}": {outcome}')

    def run(self):
        """Runs both parts in turn.

        Returns:
            None: This method returns nothing.
        """
        self.show_identifiers()
        self.show_refusals()


if __name__ == '__main__':
    IdentifiersAndRefusalsExample().run()
