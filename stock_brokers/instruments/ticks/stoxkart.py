"""Stoxkart ticks.

`bin/stoxkart/quotes` polls Stoxkart's REST quote endpoint, because the documented quote websocket could not be reached on 2026-09-15, and names each instrument `EXCHANGE:TOKEN` in Stoxkart's own exchange vocabulary: `NSE`, `BSE`, `NFO`, `BFO`, `NSECD`, `BSECD`, `MCX` and `NCDEX`. The bare token collides across exchanges, so the exchange narrows the search.

What Stoxkart's values mean, as measured against Zerodha's ticks received in the same second during the session of 2026-09-15:

- `close` is the previous session's close: TCS read 2200.80, HDFCBANK 708.25 and CRUDEOIL SEP 9717, all Zerodha's figures. What it holds after the session has not been seen, so it is trusted only before the session closes.
- On MCX every quantity is in lots, as at Zerodha: CRUDEOIL SEP read volume 6385 and open interest 15677 at both. On NSE volume matched Zerodha's exactly.
- The last trade time is a true instant: Stoxkart counts seconds from 1980, `bin/stoxkart/quotes` converts them, and CRUDEOIL SEP's matched Zerodha's to the second. Stoxkart sends no exchange timestamp.

Typical usage example:

  normalizer = StoxkartTickNormalizer()
  key = normalizer.feed_key("NSE:760946")
"""

from stock_brokers.instruments.ticks.base import CLOSE_BEFORE_SESSION_END
from stock_brokers.instruments.ticks.base import QUANTITY_FIELDS
from stock_brokers.instruments.ticks.base import FeedKey
from stock_brokers.instruments.ticks.base import TickNormalizer
from stock_brokers.instruments.ticks.base import family_segments


class StoxkartTickNormalizer(TickNormalizer):
    """Normalizes the ticks `bin/stoxkart/quotes` writes from Stoxkart's REST quotes."""

    BROKER_NAME = "stoxkart"

    EXCHANGES = {
        "NSE": (("nse",), "cash_or_index"),
        "BSE": (("bse",), "cash_or_index"),
        "NFO": (("nse",), "derivative"),
        "NSECD": (("nse",), "derivative"),
        "BFO": (("bse",), "derivative"),
        "BSECD": (("bse",), "derivative"),
        "MCX": (("mcx",), "derivative"),
        "NCDEX": (("ncdex",), "derivative"),
    }

    LOT_FIELDS = {
        "mcx": frozenset(QUANTITY_FIELDS),
    }

    CLOSE_POLICY = {
        "nse": CLOSE_BEFORE_SESSION_END,
        "bse": CLOSE_BEFORE_SESSION_END,
        "mcx": CLOSE_BEFORE_SESSION_END,
        "ncdex": CLOSE_BEFORE_SESSION_END,
    }

    def __init__(self):
        """Builds the canonical segments each Stoxkart exchange's tokens may name."""
        self._segments = {}
        for name, (exchanges, family) in self.EXCHANGES.items():
            self._segments[name] = family_segments(exchanges, family)

    def feed_key(self, instrument_token):
        """Reads the broker token and segments out of a Stoxkart `EXCHANGE:TOKEN`.

        Args:
            instrument_token (str): The tick's `instrument_token`, such as `NSE:760946`.

        Returns:
            FeedKey | None: The key, or None for a malformed token or an unknown exchange.
        """
        exchange, _, token = str(instrument_token).partition(":")
        segments = self._segments.get(exchange.strip().upper())
        if segments is None or not token.strip():
            return None
        return FeedKey(token.strip(), segments)
