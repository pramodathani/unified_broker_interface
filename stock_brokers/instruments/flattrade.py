"""
Flattrade instrument master ingestion.

Flattrade publishes eight public CSV files on S3, one per exchange and segment, all sharing the same nine-column header. The BSE equity file ends with a footer of blank rows.
"""

import pandas

from stock_brokers.instruments.base import BrokerInstruments

INSTRUMENTS_URLS = [
    "https://flattrade.s3.ap-south-1.amazonaws.com/scripmaster/NSE_Equity.csv",
    "https://flattrade.s3.ap-south-1.amazonaws.com/scripmaster/Nfo_Equity_Derivatives.csv",
    "https://flattrade.s3.ap-south-1.amazonaws.com/scripmaster/Nfo_Index_Derivatives.csv",
    "https://flattrade.s3.ap-south-1.amazonaws.com/scripmaster/Currency_Derivatives.csv",
    "https://flattrade.s3.ap-south-1.amazonaws.com/scripmaster/Commodity.csv",
    "https://flattrade.s3.ap-south-1.amazonaws.com/scripmaster/BSE_Equity.csv",
    "https://flattrade.s3.ap-south-1.amazonaws.com/scripmaster/Bfo_Index_Derivatives.csv",
    "https://flattrade.s3.ap-south-1.amazonaws.com/scripmaster/Bfo_Equity_Derivatives.csv",
]


class FlattradeInstruments(BrokerInstruments):
    """
    Downloads Flattrade's daily instrument master.

    Attributes:
        BROKER_NAME (str): Always "flattrade".
        DEDUPE_KEY_COLUMNS (list[str]): Exchange and trading symbol together.
        DEDUPE_SORT_COLUMN (str | None): Instrument, so the kept row is predictable.
    """

    BROKER_NAME = "flattrade"
    DEDUPE_KEY_COLUMNS = [
        "exchange",
        "tradingsymbol",
    ]
    DEDUPE_SORT_COLUMN = "instrument"

    def download(self):
        """
        Fetch and stack Flattrade's eight instrument master CSV files.

        Rows whose exchange or trading symbol is blank come from the BSE file's footer and are filled with empty strings so that de-duplication has a value to work with.

        Returns:
            pandas.DataFrame: Every row Flattrade published, read as text.
        """
        frames = []
        for url in INSTRUMENTS_URLS:
            frames.append(pandas.read_csv(url, dtype=str))
        frame = pandas.concat(frames, ignore_index=True)
        return frame.fillna({
            "Exchange": "",
            "Tradingsymbol": "",
            "Instrument": "",
        })
