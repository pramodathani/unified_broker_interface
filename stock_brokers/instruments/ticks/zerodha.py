"""
Zerodha (Kite) ticks.

A Kite instrument token carries its segment in the low byte, so the token alone says which
instruments it can be - no prefix to parse. The segment codes are the ones
`stock_brokers/instruments/historical/zerodha.py` resolves candle series with, repeated here rather
than imported because that module pulls in the Kite API client; the offline suite checks the two
tables agree.

What Kite's values mean, as measured against the stored ticks:

- `close` is the previous session's close at every hour: RELIANCE read 1274.0 in every row from the
  evening of 2026-09-12 through the Sunday reconnect, while Dhan read that Friday's own close.
- On MCX every quantity is in lots. At 22:46:57 on 2026-09-11 CRUDEOIL SEP read volume 67958, open
  interest 18095, last quantity 2 and a best bid of 1 at both Zerodha and Dhan - a day's volume of
  67958 barrels would be absurd, 67958 lots of 100 barrels is not.
- On NSE and BSE every quantity is taken to be in shares or contract units, which a live session checks.
- `exchange_timestamp` is when the exchange sent the packet, not when the instrument last traded,
  and `last_trade_time` is the trade. Both are true epochs.
"""

from stock_brokers.instruments.ticks.base import (CLOSE_ALWAYS, QUANTITY_FIELDS, FeedKey, TickNormalizer,
                                                  family_segments)

class ZerodhaTickNormalizer(TickNormalizer):
    """
    Normalizes Zerodha ticks.
    """

    BROKER_NAME = "zerodha"

    # Low byte of the instrument token to (exchanges, family).
    SEGMENT_CODES = {
        1: (("nse",), "cash"),              # NSE
        2: (("nse",), "derivative"),        # NFO
        3: (("nse",), "derivative"),        # CDS
        4: (("bse",), "cash"),              # BSE
        5: (("bse",), "derivative"),        # BFO
        6: (("bse",), "derivative"),        # BCD
        7: (("mcx",), "derivative"),        # MCX
        9: (("nse", "bse"), "index"),       # INDICES, both exchanges' indices
        12: (("nse",), "derivative"),       # NCO
    }

    LOT_FIELDS = {"mcx": frozenset(QUANTITY_FIELDS)}

    CLOSE_POLICY = {"nse": CLOSE_ALWAYS, "bse": CLOSE_ALWAYS, "mcx": CLOSE_ALWAYS}

    def __init__(self):
        self._segments = {code: family_segments(exchanges, family)
                          for code, (exchanges, family) in self.SEGMENT_CODES.items()}

    def feed_key(self, instrument_token):
        """
        The broker token and segments for a Kite instrument token.

        Args:
            instrument_token (int | str): The tick's `instrument_token`, an integer.

        Returns:
            FeedKey | None: The key, or None for a token that is not a number or whose segment code is unknown.
        """
        try:
            token = int(instrument_token)
        except (TypeError, ValueError):
            return None
        segments = self._segments.get(token & 0xff)
        if segments is None:
            return None
        return FeedKey(str(token), segments)

    def tick_spelling(self, subscription_token):
        """
        A Kite subscription token as ticks carry it: an integer.

        Args:
            subscription_token (str): A member of `subscriptions_zerodha`, such as "738561".

        Returns:
            int | None: The token, or None when it is not a number.
        """
        try:
            return int(subscription_token)
        except (TypeError, ValueError):
            return None
