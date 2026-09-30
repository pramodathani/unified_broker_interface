"""Builds IND Money scrip codes from its instrument master, reads what a scrip code says about its instrument, and classifies IND Money's refusals.

The chart endpoint wants a scrip code whose prefix comes from the segment rather than the exchange: a derivative is recorded under NSE in the instrument master but must be asked about as `NFO`, and asking with `NSE` quietly answers nothing. BSE derivatives are left out, because the endpoint refuses every prefix tried for them. IND Money's expiry, written like `09/29/2026 14:00`, is turned into a date for the queue's priority. The program gives the downloader a stand-in database connection whose cursor answers with four rows, one of them a BSE derivative that is dropped.

`identifier_parts` splits a scrip code into its prefix and security id, and `series_context`, a classmethod that needs no downloader, reads the exchange and segments the prefix names.

Last, the program fetches through a stand-in for `INDMoneyAPI` that raises the `INDMoneyAPIException` each of three refusals produces: an unknown scrip code retires the series, a rate limit is a throttle and a 401 is a dead session. The downloader is built without its constructor, as in `test_runs/candle_parse.py`, so nothing connects to PostgreSQL or logs in.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/indmoney/IndMoneyCandles/example_2_scrip_codes_and_refusals.py
"""

import datetime

from stock_brokers.api.indmoney import (
    INDMoneyAPIException,
)
from stock_brokers.instruments.historical.base import (
    CandleError,
)
from stock_brokers.instruments.historical.indmoney import (
    IndMoneyCandles,
)


class InstrumentMasterCursor:
    """A stand-in database cursor that answers the instrument master query with fixed rows.

    Attributes:
        rows (list): The rows `fetchall` returns.
    """

    def __init__(self, rows):
        """Holds the rows to answer with.

        Args:
            rows (list): Tuples of (exchange, segment, security id, instrument type, expiry).

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
    """A stand-in PostgreSQL connection over four rows of IND Money's instrument master.

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
                'NSE',
                'E',
                '2885',
                'EQUITY',
                None,
            ),
            (
                'BSE',
                'E',
                '500325',
                'EQUITY',
                None,
            ),
            (
                'NSE',
                'D',
                '52175',
                'FUTSTK',
                '09/29/2026 14:00',
            ),
            (
                'BSE',
                'D',
                '1144412',
                'FUTSTK',
                '09/24/2026 14:00',
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


class RefusingIndMoneyAPI:
    """A stand-in for `INDMoneyAPI` that refuses with a chosen error.

    Attributes:
        code (int): The HTTP status the refusal carries.
        message (str): The message the refusal carries.
    """

    def __init__(self, code, message):
        """Holds the refusal to raise.

        Args:
            code (int): The HTTP status.
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
            INDMoneyAPIException: Always, carrying the chosen status and message.
        """
        raise INDMoneyAPIException(code=self.code, message=self.message)


class ScripCodesAndRefusalsExample:
    """Lists scrip codes, reads them, and classifies three refusals.

    Attributes:
        candles (IndMoneyCandles): The downloader being shown.
    """

    def __init__(self):
        """Builds the downloader around the stand-in connection without running its constructor.

        Returns:
            None: This method returns nothing.
        """
        self.candles = object.__new__(IndMoneyCandles)
        self.candles._connection = InstrumentMasterConnection()

    def show_scrip_codes(self):
        """Lists the instruments and reads each scrip code.

        Returns:
            None: This method returns nothing.
        """
        instruments = self.candles.instruments()
        print(f'Instruments to download: {len(instruments)} of 4 rows')
        for scrip_code, instrument_type, expiry in instruments:
            prefix, security_id = self.candles.identifier_parts(scrip_code)
            context = IndMoneyCandles.series_context(scrip_code)
            print(f'{scrip_code}: prefix {prefix}, security id {security_id}, {instrument_type}, expiry {expiry}, exchange {context.exchange}, {len(context.segments)} segments to search')

    def show_refusals(self):
        """Fetches through three refusing stand-ins and prints what each became.

        Returns:
            None: This method returns nothing.
        """
        refusals = [
            (
                400,
                'Invalid scrip codes: NSE_99999999',
            ),
            (
                429,
                'Rate limit exceeded',
            ),
            (
                401,
                'Unauthorized',
            ),
        ]
        for code, message in refusals:
            self.candles._api = RefusingIndMoneyAPI(code, message)
            try:
                self.candles.fetch_candles(
                    'NSE_99999999',
                    'day',
                    datetime.date(2025, 9, 1),
                    datetime.date(2026, 9, 1),
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
        self.show_scrip_codes()
        self.show_refusals()


if __name__ == '__main__':
    ScripCodesAndRefusalsExample().run()
