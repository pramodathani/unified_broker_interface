"""
Groww instrument master ingestion.

Groww publishes one public CSV covering every exchange and segment it supports.
"""

import pandas

from stock_brokers.instruments.base import BrokerInstruments

INSTRUMENTS_URL = "https://growwapi-assets.groww.in/instruments/instrument.csv"


class GrowwInstruments(BrokerInstruments):
    """
    Downloads Groww's daily instrument master.

    Attributes:
        BROKER_NAME (str): Always "groww".
        DEDUPE_KEY_COLUMNS (list[str]): Exchange, segment and trading symbol together.
        DEDUPE_SORT_COLUMN (str | None): Series, so the kept row is predictable.
    """

    BROKER_NAME = "groww"
    DEDUPE_KEY_COLUMNS = [
        "exchange",
        "segment",
        "trading_symbol",
    ]
    DEDUPE_SORT_COLUMN = "series"

    def download(self):
        """
        Fetch Groww's single instrument master CSV.

        Returns:
            pandas.DataFrame: Every row Groww published, read as text.
        """
        return pandas.read_csv(INSTRUMENTS_URL, dtype=str)
