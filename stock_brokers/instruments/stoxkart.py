"""
Stoxkart instrument master ingestion.

Stoxkart publishes one public CSV of roughly thirty-six megabytes covering every exchange it supports.
"""

import pandas

from stock_brokers.instruments.base import BrokerInstruments

INSTRUMENTS_URL = "https://openapi.stoxkart.com/scrip-master/csv"


class StoxkartInstruments(BrokerInstruments):
    """
    Downloads Stoxkart's daily instrument master.

    Attributes:
        BROKER_NAME (str): Always "stoxkart".
        DEDUPE_KEY_COLUMNS (list[str]): Exchange and token together.
        DEDUPE_SORT_COLUMN (str | None): Series, so the kept row is predictable.
    """

    BROKER_NAME = "stoxkart"
    DEDUPE_KEY_COLUMNS = [
        "exchange",
        "token",
    ]
    DEDUPE_SORT_COLUMN = "series"

    def download(self):
        """
        Fetch Stoxkart's single instrument master CSV.

        Returns:
            pandas.DataFrame: Every row Stoxkart published, read as text.
        """
        return pandas.read_csv(INSTRUMENTS_URL, dtype=str)
