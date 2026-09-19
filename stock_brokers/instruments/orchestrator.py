"""
Runs instrument master ingestion across every broker.

Each broker is downloaded in its own try/except, so one broker's endpoint being down, or its
token having expired, never costs the others their snapshot for the day. That matters more here
than it would elsewhere: nine of the ten brokers publish only today's file, and Kotak's URL is
stamped with today's date, so a snapshot missed is a snapshot that can never be fetched later.
"""

from datetime import date

from stock_brokers.instruments.zerodha import ZerodhaInstruments
from stock_brokers.instruments.dhan import DhanInstruments
from stock_brokers.instruments.flattrade import FlattradeInstruments
from stock_brokers.instruments.shoonya import ShoonyaInstruments
from stock_brokers.instruments.fyers import FyersInstruments
from stock_brokers.instruments.groww import GrowwInstruments
from stock_brokers.instruments.kotak import KotakInstruments
from stock_brokers.instruments.indmoney import IndMoneyInstruments
from stock_brokers.instruments.wisdom_capital import WisdomCapitalInstruments
from stock_brokers.instruments.stoxkart import StoxkartInstruments

INGESTERS = {
    "zerodha": ZerodhaInstruments,
    "dhan": DhanInstruments,
    "flattrade": FlattradeInstruments,
    "shoonya": ShoonyaInstruments,
    "fyers": FyersInstruments,
    "groww": GrowwInstruments,
    "kotak": KotakInstruments,
    "indmoney": IndMoneyInstruments,
    "wisdom_capital": WisdomCapitalInstruments,
    "stoxkart": StoxkartInstruments,
}

INSTRUMENT_BROKERS = tuple(INGESTERS)

def ingest_one(broker_name, download_date=None, bootstrap=False):
    """
    Ingest one broker's instrument master, catching any failure rather than raising.

    - `broker_name` is the name of the broker to ingest.
    - `download_date` is the snapshot date to record, defaulting to today.
    - `bootstrap` replaces that date's stored rows rather than skipping when already ingested.

    Returns a `(rows, deviation, error)` triple, where `deviation` is the row count canary's
    verdict and `error` is None on success.
    """
    try:
        ingester = INGESTERS[broker_name]()
        rows = ingester.ingest(download_date=download_date, bootstrap=bootstrap)
        deviation = ingester.check_row_count_deviation(download_date or date.today()) if rows else None
        return rows, deviation, None
    except Exception as exception:
        return 0, None, f"{type(exception).__name__}: {str(exception).splitlines()[0]}"

def ingest_all(brokers=INSTRUMENT_BROKERS, download_date=None, bootstrap=False):
    """
    Ingest every named broker in turn, isolating each one's failure from the rest.

    - `brokers` is the list of broker names to ingest.
    - `download_date` is the snapshot date to record, defaulting to today.
    - `bootstrap` replaces that date's stored rows rather than skipping when already ingested.
    """
    return {broker_name: ingest_one(broker_name, download_date, bootstrap)
            for broker_name in brokers}
