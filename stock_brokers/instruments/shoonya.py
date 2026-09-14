"""
Shoonya instrument master ingestion.

Shoonya publishes seven public ZIP archives, one per exchange, each holding a single comma-separated text file. The per-exchange files do not all carry the same columns, so stacking them produces the union, and every line ends with a trailing comma.
"""

import zipfile
from io import BytesIO, StringIO

import pandas
import requests

from stock_brokers.instruments.base import BrokerInstruments

INSTRUMENTS_URLS = [
    "https://api.shoonya.com/NSE_symbols.txt.zip",
    "https://api.shoonya.com/NFO_symbols.txt.zip",
    "https://api.shoonya.com/CDS_symbols.txt.zip",
    "https://api.shoonya.com/MCX_symbols.txt.zip",
    "https://api.shoonya.com/BSE_symbols.txt.zip",
    "https://api.shoonya.com/BFO_symbols.txt.zip",
    "https://api.shoonya.com/NCX_symbols.txt.zip",
]

DOWNLOAD_TIMEOUT_SECONDS = 120


class ShoonyaInstruments(BrokerInstruments):
    """
    Downloads Shoonya's daily instrument master.

    Attributes:
        BROKER_NAME (str): Always "shoonya".
        DEDUPE_KEY_COLUMNS (list[str]): Exchange and trading symbol together.
        DEDUPE_SORT_COLUMN (str | None): Instrument, so the kept row is predictable.
    """

    BROKER_NAME = "shoonya"
    DEDUPE_KEY_COLUMNS = [
        "exchange",
        "tradingsymbol",
    ]
    DEDUPE_SORT_COLUMN = "instrument"

    def download(self):
        """
        Fetch Shoonya's seven ZIP archives and stack the text file inside each.

        The files are decoded as latin-1 because that decoding never fails on a byte sequence, and the content is plain ASCII in practice.

        Returns:
            pandas.DataFrame: Every row Shoonya published, read as text.

        Raises:
            requests.HTTPError: If any archive cannot be downloaded.
            ValueError: If the archives download but hold no readable instrument data.
        """
        frames = []
        for url in INSTRUMENTS_URLS:
            response = requests.get(url, timeout=DOWNLOAD_TIMEOUT_SECONDS)
            response.raise_for_status()
            with zipfile.ZipFile(BytesIO(response.content)) as archive:
                for member_name in archive.namelist():
                    if not member_name.lower().endswith((".csv", ".txt")):
                        continue
                    text_content = archive.read(member_name).decode("latin-1")
                    frame = pandas.read_csv(StringIO(text_content), dtype=str)
                    frame["source_zip_url"] = url
                    frame["source_file_name"] = member_name
                    frames.append(frame)
        if not frames:
            raise ValueError("Shoonya's archives downloaded but held no readable instrument data.")
        return pandas.concat(frames, ignore_index=True)
