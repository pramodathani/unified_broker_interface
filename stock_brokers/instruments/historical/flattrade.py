"""
Flattrade historical candle download.

Flattrade runs the Noren platform, so everything about the two endpoints, the refusal shapes and
the field names lives in `noren.py`, shared with Shoonya. What is particular to Flattrade is here: its host, its rate, and
how far back its deployment keeps data.

Measured on 2026-09-12 against RELIANCE: `EODChartData` reaches 2019-12-03 and no further, some
sixteen hundred and fifty daily bars, and `TPSeries` keeps a rolling year of intraday bars with
January to April 2026 missing from the middle of it.
"""

import datetime

from stock_brokers.instruments.historical.noren import NorenCandles

BASE_URL = "https://piconnect.flattrade.in/PiConnectAPI"

class FlattradeCandles(NorenCandles):
    """
    Downloads Flattrade's historical candles.
    """

    BROKER_NAME = "flattrade"
    BASE_URL = BASE_URL

    # Flattrade documents ten requests a second, ten times what Shoonya allows on the same
    # platform, and publishes no daily cap.
    REQUESTS_PER_SECOND = 10.0
    REQUESTS_PER_DAY = None

    # The daily history, which is the deeper of the two. Intraday reaches back about a year and
    # stops there on its own, three empty windows after it runs out.
    EARLIEST_AVAILABLE_DATE = datetime.date(2019, 1, 1)

    def _build_api(self):
        """
        Construct the authenticated Flattrade API class.
        """
        from stock_brokers.api.flattrade import FlattradeAPI

        return FlattradeAPI()
