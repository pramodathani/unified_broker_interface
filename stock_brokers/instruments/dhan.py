"""
Dhan instrument master ingestion.

Dhan publishes one public detailed scrip master CSV. Every line ends with a trailing comma, which the base class drops as an empty artifact column.
"""

import pandas

from stock_brokers.instruments.base import BrokerInstruments

INSTRUMENTS_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"


class DhanInstruments(BrokerInstruments):
    """
    Downloads Dhan's daily instrument master.

    Attributes:
        BROKER_NAME (str): Always "dhan".
        DEDUPE_KEY_COLUMNS (list[str]): Exchange, segment and security identifier together.
        DEDUPE_SORT_COLUMN (str | None): Series, so the kept row is predictable.
    """

    BROKER_NAME = "dhan"
    DEDUPE_KEY_COLUMNS = [
        "exch_id",
        "segment",
        "security_id",
    ]
    DEDUPE_SORT_COLUMN = "series"

    def download(self):
        """
        Fetch Dhan's single detailed scrip master CSV.

        Returns:
            pandas.DataFrame: Every row Dhan published, read as text.
        """
        return pandas.read_csv(INSTRUMENTS_URL, dtype=str)
