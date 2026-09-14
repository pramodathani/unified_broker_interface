"""
Fyers instrument master ingestion.

Fyers publishes seven public CSV files, one per exchange and segment. None of them carries a header row, so the column names are declared here.
"""

import pandas

from stock_brokers.instruments.base import BrokerInstruments

INSTRUMENTS_URLS = [
    "https://public.fyers.in/sym_details/NSE_CD.csv",
    "https://public.fyers.in/sym_details/NSE_FO.csv",
    "https://public.fyers.in/sym_details/NSE_COM.csv",
    "https://public.fyers.in/sym_details/NSE_CM.csv",
    "https://public.fyers.in/sym_details/BSE_CM.csv",
    "https://public.fyers.in/sym_details/BSE_FO.csv",
    "https://public.fyers.in/sym_details/MCX_COM.csv",
]

COLUMN_NAMES = [
    "fytoken",
    "symbol_details",
    "exchange_instrument_type",
    "minimum_lot_size",
    "tick_size",
    "isin",
    "trading_session",
    "last_update_date",
    "expiry_date",
    "symbol_ticker",
    "exchange",
    "segment",
    "scrip_code",
    "underlying_symbol",
    "underlying_scrip_code",
    "strike_price",
    "option_type",
    "underlying_fytoken",
    "reserved_column1",
    "reserved_column2",
    "reserved_column3",
]


class FyersInstruments(BrokerInstruments):
    """
    Downloads Fyers' daily instrument master.

    Attributes:
        BROKER_NAME (str): Always "fyers".
        DEDUPE_KEY_COLUMNS (list[str]): The symbol ticker, which Fyers makes unique across every file.
        DEDUPE_SORT_COLUMN (str | None): Unused, the key alone is unambiguous.
    """

    BROKER_NAME = "fyers"
    DEDUPE_KEY_COLUMNS = [
        "symbol_ticker",
    ]
    DEDUPE_SORT_COLUMN = None

    def download(self):
        """
        Fetch and stack Fyers' seven headerless instrument master CSV files.

        Returns:
            pandas.DataFrame: Every row Fyers published, read as text, with the declared column names applied.
        """
        frames = []
        for url in INSTRUMENTS_URLS:
            frame = pandas.read_csv(url, dtype=str, header=None, names=COLUMN_NAMES)
            frames.append(frame)
        return pandas.concat(frames, ignore_index=True)
