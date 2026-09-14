"""
Zerodha instrument master ingestion.

Zerodha publishes one public CSV covering every exchange it supports.
"""

import pandas

from stock_brokers.instruments.base import BrokerInstruments

INSTRUMENTS_URL = "https://api.kite.trade/instruments"

class ZerodhaInstruments(BrokerInstruments):
    """
    Downloads Zerodha's daily instrument master.

    The instrument token is unique across every exchange, so it alone is an unambiguous key and
    nothing has to be sorted before de-duplicating.
    """

    BROKER_NAME = "zerodha"
    DEDUPE_KEY_COLUMNS = ["instrument_token"]
    DEDUPE_SORT_COLUMN = None

    def download(self):
        """Fetch Zerodha's single instrument master CSV, read as text."""
        return pandas.read_csv(INSTRUMENTS_URL, dtype=str)
