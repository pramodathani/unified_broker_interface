"""
The brokers whose historical candles can be downloaded, and the three whose cannot.

Seven of the ten brokers serve historical candles. The other three are recorded here with the
reason rather than being silently absent, because "why is Kotak not backfilling" is a question
that will otherwise be asked more than once.
"""

import importlib

# Broker to (module, class). Imported lazily: several broker API modules pull in Selenium at
# module level and a process downloading one broker should not pay for the others.
DOWNLOADERS = {
    "zerodha": ("stock_brokers.instruments.historical.zerodha", "ZerodhaCandles"),
    "dhan": ("stock_brokers.instruments.historical.dhan", "DhanCandles"),
    "fyers": ("stock_brokers.instruments.historical.fyers", "FyersCandles"),
    "indmoney": ("stock_brokers.instruments.historical.indmoney", "IndMoneyCandles"),
    "flattrade": ("stock_brokers.instruments.historical.flattrade", "FlattradeCandles"),
    "shoonya": ("stock_brokers.instruments.historical.shoonya", "ShoonyaCandles"),
    "wisdom_capital": ("stock_brokers.instruments.historical.wisdom_capital",
                       "WisdomCapitalCandles"),
}

# Brokers with no usable historical endpoint, and why. Checked before assuming a gap is a bug.
UNSUPPORTED = {
    "groww": "returns 403 on the historical endpoint; it is an entitlement, not a bug",
    "kotak": "publishes no historical candle endpoint at all",
    "stoxkart": "no candle path",
}

CANDLE_BROKERS = tuple(DOWNLOADERS)

def downloader_for(broker_name):
    """
    The candle downloader class for a broker.

    - `broker_name` is the name of the broker.
    """
    if broker_name in UNSUPPORTED:
        raise ValueError(f"{broker_name} has no historical candles: {UNSUPPORTED[broker_name]}")
    if broker_name not in DOWNLOADERS:
        raise ValueError(f"No candle downloader for {broker_name}. "
                         f"Known: {', '.join(sorted(DOWNLOADERS))}")
    module_name, class_name = DOWNLOADERS[broker_name]
    return getattr(importlib.import_module(module_name), class_name)
