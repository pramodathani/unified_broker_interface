"""
Ticks from brokers on the Noren platform: Flattrade and Shoonya.

Noren names an instrument as `EXCHANGE|TOKEN` in its own exchange vocabulary - `NFO` for NSE
derivatives, `CDS` for NSE currency, `MCX` - and stores the bare token in
unified.broker_mappings, where it collides across segments, so the exchange is what narrows the
search.

What Noren's values mean, as measured against the stored ticks of 2026-09-12 and 2026-09-13:

- `c` is the previous session's close while a session runs and the session's own close after it. In
  Saturday's mock session Flattrade's RELIANCE read `c` 1257.5, Friday's close, against a mock last
  price of 1270.1; after the exchanges reset on Sunday, Shoonya's read 1257.5 for both. So, as for
  Dhan, it is used only before the session's close.
- On MCX, open interest is in lots - CRUDEOIL SEP 17552 and GOLD OCT 9618 at Shoonya, both the same
  as Zerodha - and the other MCX quantities are taken to be lots too, which a live session checks.
- `ft` is a true instant: Flattrade's 21:02:12 for RELIANCE's last mock trade is the second Wisdom
  Capital's corrected last trade time shows. The last trade time is parsed in the market feed.
"""

from stock_brokers.instruments.ticks.base import (CLOSE_BEFORE_SESSION_END, QUANTITY_FIELDS, FeedKey,
                                                  TickNormalizer, family_segments)

class NorenTickNormalizer(TickNormalizer):
    """
    Normalizes ticks from a Noren platform broker. A subclass sets BROKER_NAME.
    """

    # Noren exchange to (exchanges, family).
    EXCHANGES = {
        "NSE": (("nse",), "cash_or_index"),
        "BSE": (("bse",), "cash_or_index"),
        "NFO": (("nse",), "derivative"),
        "CDS": (("nse",), "derivative"),
        "NCO": (("nse",), "derivative"),
        "BFO": (("bse",), "derivative"),
        "BCD": (("bse",), "derivative"),
        "MCX": (("mcx",), "derivative"),
        "NCX": (("ncdex",), "derivative"),
        "NCDEX": (("ncdex",), "derivative"),
    }

    LOT_FIELDS = {"mcx": frozenset(QUANTITY_FIELDS), "ncdex": frozenset(QUANTITY_FIELDS)}

    CLOSE_POLICY = {exchange: CLOSE_BEFORE_SESSION_END for exchange in ("nse", "bse", "mcx", "ncdex")}

    def __init__(self):
        self._segments = {name: family_segments(exchanges, family)
                          for name, (exchanges, family) in self.EXCHANGES.items()}

    def feed_key(self, instrument_token):
        """
        The broker token and segments for a Noren `EXCHANGE|TOKEN`.

        Args:
            instrument_token (str): The tick's `instrument_token`, such as "MCX|565899".

        Returns:
            FeedKey | None: The key, or None for a malformed token or an unknown exchange.
        """
        exchange, _, token = str(instrument_token).partition("|")
        segments = self._segments.get(exchange.strip().upper())
        if segments is None or not token.strip():
            return None
        return FeedKey(token.strip(), segments)
