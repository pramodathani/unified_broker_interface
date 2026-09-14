"""
Kotak instrument master ingestion.

Kotak publishes seven public CSV files under a URL path stamped with the day's date. Two of them sit under a different path prefix from the other five and carry one extra column.
"""

import pandas

from stock_brokers.instruments.base import BrokerInstruments

BASE_URL = "https://lapi.kotaksecurities.com/wso2-scripmaster/v1/prod"

TRANSFORMED_FILE_NAMES = [
    "cde_fo",
    "mcx_fo",
    "nse_fo",
    "bse_fo",
    "nse_com",
]

TRANSFORMED_V1_FILE_NAMES = [
    "bse_cm-v1",
    "nse_cm-v1",
]


class KotakInstruments(BrokerInstruments):
    """
    Downloads Kotak's daily instrument master.

    Attributes:
        BROKER_NAME (str): Always "kotak".
        DEDUPE_KEY_COLUMNS (list[str]): Exchange segment and trading symbol together.
        DEDUPE_SORT_COLUMN (str | None): Instrument type, so the kept row is predictable.
    """

    BROKER_NAME = "kotak"
    DEDUPE_KEY_COLUMNS = [
        "pexchseg",
        "ptrdsymbol",
    ]
    DEDUPE_SORT_COLUMN = "pinsttype"

    def download(self):
        """
        Fetch and stack Kotak's seven instrument master CSV files for today.

        Kotak serves these files under today's date only, so a backfill of an earlier date is not possible from this source.

        Returns:
            pandas.DataFrame: Every row Kotak published, read as text.
        """
        date_text = pandas.Timestamp.today().strftime("%Y-%m-%d")

        frames = []
        for file_name in TRANSFORMED_FILE_NAMES:
            frames.append(pandas.read_csv(f"{BASE_URL}/{date_text}/transformed/{file_name}.csv", dtype=str))
        for file_name in TRANSFORMED_V1_FILE_NAMES:
            frames.append(pandas.read_csv(f"{BASE_URL}/{date_text}/transformed-v1/{file_name}.csv", dtype=str))
        return pandas.concat(frames, ignore_index=True)
