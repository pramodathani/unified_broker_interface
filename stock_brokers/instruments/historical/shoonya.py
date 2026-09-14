"""
Shoonya historical candle download.

Shoonya runs the Noren platform, so the two endpoints, the refusal shapes and the field names all
live in `noren.py`, as it does for Flattrade. What is
particular to Shoonya is here: its host, its rate, and how far back its deployment keeps data.

Measured on 2026-09-12 against RELIANCE: `EODChartData` holds a rolling five years, reaching
2021-09-13 and no further, and `TPSeries` a rolling year of intraday bars with January to April
2026 missing from the middle of it - the same hole Flattrade has, which suggests it belongs to
the platform rather than to either broker.

Shoonya also lists NCDEX, which Flattrade does not. That costs nothing here: the exchange comes
straight out of Shoonya's own scrip files rather than being translated, so an exchange the other
deployment has never heard of needs no code at all.
"""

import datetime

from stock_brokers.instruments.historical.noren import NorenCandles

BASE_URL = "https://api.shoonya.com/NorenWClientAPI"

class ShoonyaCandles(NorenCandles):
    """
    Downloads Shoonya's historical candles.
    """

    BROKER_NAME = "shoonya"
    BASE_URL = BASE_URL

    # Shoonya's rate limits page documents about one request a second for market data REST, with
    # a lower burst allowance for historical. It publishes no daily cap.
    REQUESTS_PER_SECOND = 1.0
    REQUESTS_PER_DAY = None

    # The daily history, which is the deeper of the two, and it is a rolling five years rather
    # than a fixed date: it moved with the calendar between measurements.
    EARLIEST_AVAILABLE_DATE = datetime.date(2021, 1, 1)

    def _build_api(self):
        """
        Construct the authenticated Shoonya API class.
        """
        from stock_brokers.api.shoonya import ShoonyaAPI

        return ShoonyaAPI()
