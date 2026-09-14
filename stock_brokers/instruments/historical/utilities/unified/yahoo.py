"""
Daily history and split events from Yahoo Finance, for the adjustment factor builder.

One request per ticker: `Ticker.history(period="max", auto_adjust=False, actions=True)`. With
`auto_adjust=False`, Yahoo's `Close` is adjusted for splits, bonuses, demergers and rights issues but
not for dividends, and `Stock Splits` lists the split and bonus events Yahoo knows of - 2.0 for a
two-for-one split or a 1:1 bonus, 0.3 for a consolidation. Demergers are never listed; they show only
in how `Close` moves against the raw price, which is what `factors` measures.

Tickers are tried in order: NSE instruments as SYMBOL.NS; BSE instruments as SYMBOL.BO, then as the
BSE scrip code, 500325.BO, then - for a company also listed on NSE - as SYMBOL.NS. Yahoo keeps many
BSE tickers only as stubs: RELIANCE.BO returns two rows, and PIDILITIND.BO and 500331.BO one and none.
A form that does not cover the raw history is passed over for the next.

Dates are read straight off the index, without converting time zones: .NS and .BO histories are
labelled Asia/Kolkata, but scrip code tickers come back labelled America/New_York while still
carrying Indian trading dates, and converting them would move every bar back a day.

Yahoo rate limits, so requests are paced at roughly one a second with jitter, and a rate limit
answer backs off rather than pressing on.
"""

import random
import time

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

from utilities.configurations import get_logger

LOGGER = get_logger("unified_prices")

# Seconds between requests, before jitter.
PACE_SECONDS = 1.0

# Back-off after a rate limit answer, doubling each time, and how many to take before giving up.
RATE_LIMIT_BACKOFF_SECONDS = 60
RATE_LIMIT_ATTEMPTS = 4

# A ticker form must cover at least this share of the raw trading days it is compared with.
MINIMUM_COVERAGE = 0.8

YahooHistory = tuple  # (closes: dict[date, float], events: dict[date, float])

class YahooClient:
    """
    Paced access to Yahoo Finance daily history.

    Attributes:
        last_request (float): When the last request was sent, on the monotonic clock.
    """

    def __init__(self):
        """
        Build a client; nothing is requested until asked.

        Returns:
            None: This function returns nothing.
        """
        self.last_request = 0.0

    def pace(self):
        """
        Sleep until the next request is allowed.

        Returns:
            None: This function returns nothing.
        """
        wait = PACE_SECONDS + random.uniform(0, 0.5) - (time.monotonic() - self.last_request)
        if wait > 0:
            time.sleep(wait)
        self.last_request = time.monotonic()

    def history(self, ticker):
        """
        One ticker's full daily history.

        Args:
            ticker (str): A Yahoo ticker, for example "RELIANCE.NS".

        Returns:
            tuple: (closes, events) - closes maps datetime.date to Yahoo's Close, events maps the
                date of each listed split or bonus to its ratio. Both are empty when Yahoo has nothing.
        """
        backoff = RATE_LIMIT_BACKOFF_SECONDS
        for attempt in range(1, RATE_LIMIT_ATTEMPTS + 1):
            self.pace()
            try:
                frame = yf.Ticker(ticker).history(period="max", auto_adjust=False, actions=True)
                break
            except YFRateLimitError:
                if attempt == RATE_LIMIT_ATTEMPTS:
                    raise
                LOGGER.warning("Yahoo rate limited on %s, waiting %ds", ticker, backoff)
                time.sleep(backoff)
                backoff *= 2

        closes = {}
        events = {}
        if frame is None or frame.empty:
            return closes, events
        splits = frame["Stock Splits"] if "Stock Splits" in frame else pd.Series(0.0, index=frame.index)
        for moment, close, split in zip(frame.index, frame["Close"], splits):
            day = moment.date()
            if pd.notna(close) and close > 0:
                closes[day] = float(close)
            if pd.notna(split) and split not in (0, 1):
                events[day] = float(split)
        return closes, events

def ticker_forms(exchange, symbol, scrip_code, listed_on_nse=False):
    """
    The Yahoo tickers to try for an instrument, in order.

    Args:
        exchange (str): "nse" or "bse".
        symbol (str): The exchange trading symbol.
        scrip_code (str | None): The BSE scrip code, for BSE instruments.
        listed_on_nse (bool): Whether a BSE instrument's symbol is also listed on NSE.

    Returns:
        list[tuple[str, str]]: (ticker, kind) pairs, kind being "ticker", "scrip_code" or "nse_ticker".
    """
    if exchange == "nse":
        return [(f"{symbol}.NS", "ticker")]
    forms = [(f"{symbol}.BO", "ticker")]
    if scrip_code:
        forms.append((f"{scrip_code}.BO", "scrip_code"))
    if listed_on_nse:
        # Yahoo keeps some BSE tickers only as stubs; the company's actions are the same on NSE.
        forms.append((f"{symbol}.NS", "nse_ticker"))
    return forms

def coverage(closes, raw_days):
    """
    The share of raw trading days a Yahoo history has a close for.

    Args:
        closes (dict): Yahoo closes by date.
        raw_days (list[datetime.date]): The raw bars' dates.

    Returns:
        float: Between 0 and 1.
    """
    if not raw_days:
        return 0.0
    return sum(1 for day in raw_days if day in closes) / len(raw_days)
