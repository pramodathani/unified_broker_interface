"""
Dhan ticks.

Dhan identifies an instrument by an exchange segment and a security id. Its market feed publishes
the segment as the numeric code from the packet header - `5:565899` - while its subscription set
spells it by name - `MCX_COMM:565899` - so both spellings are accepted. The security id is stored
bare in unified.broker_mappings and is reused across segments (2885 is RELIANCE on NSE and a
currency option too), which is why the segment has to come along.

What Dhan's values mean, as measured against the stored ticks of 2026-09-11 to 2026-09-13:

- `close` is the previous session's close while the session runs - CRUDEOIL SEP read 9722.0 at 22:46
  on 2026-09-11, the same as Zerodha - and is the day's own close after it: RELIANCE read 1257.5 from
  the evening of 2026-09-12 onwards, where Zerodha's previous close read 1274.0. So it is used only
  before the session's close, and the previous close already seen carries through the evening. An
  NSE in-session reading has not been observed yet and is on the live checklist.
- On MCX every quantity is in lots, identical to Zerodha's at the same moment (volume 67958, open
  interest 18095). `oi_day_high` and `oi_day_low` arrive as 0 and are dropped.
- Prices arrive as float32 and carry noise past the second place; rounding in the base class removes it.
- The feed sends no exchange timestamp, and its last trade time is corrected to a true epoch in the
  market feed.
"""

from stock_brokers.instruments.ticks.base import (CLOSE_BEFORE_SESSION_END, QUANTITY_FIELDS, FeedKey,
                                                  TickNormalizer, family_segments)

class DhanTickNormalizer(TickNormalizer):
    """
    Normalizes Dhan ticks.
    """

    BROKER_NAME = "dhan"

    # Dhan's numeric segment code to (exchanges, family), per the DhanHQ v2 annexure.
    SEGMENT_CODES = {
        0: (("nse", "bse"), "index"),       # IDX_I
        1: (("nse",), "cash"),              # NSE_EQ
        2: (("nse",), "derivative"),        # NSE_FNO
        3: (("nse",), "derivative"),        # NSE_CURRENCY
        4: (("bse",), "cash"),              # BSE_EQ
        5: (("mcx",), "derivative"),        # MCX_COMM
        7: (("bse",), "derivative"),        # BSE_CURRENCY
        8: (("bse",), "derivative"),        # BSE_FNO
    }

    # The segment names the subscription set uses, to their numeric codes.
    SEGMENT_NAMES = {
        "IDX_I": 0, "NSE_EQ": 1, "NSE_FNO": 2, "NSE_CURRENCY": 3,
        "BSE_EQ": 4, "MCX_COMM": 5, "BSE_CURRENCY": 7, "BSE_FNO": 8,
    }

    LOT_FIELDS = {"mcx": frozenset(QUANTITY_FIELDS)}

    CLOSE_POLICY = {"nse": CLOSE_BEFORE_SESSION_END, "bse": CLOSE_BEFORE_SESSION_END,
                    "mcx": CLOSE_BEFORE_SESSION_END}

    TRUSTS_EXCHANGE_TIME = False

    def __init__(self):
        self._segments = {code: family_segments(exchanges, family)
                          for code, (exchanges, family) in self.SEGMENT_CODES.items()}

    def feed_key(self, instrument_token):
        """
        The broker token and segments for a Dhan `SEGMENT:SECURITY_ID` token.

        Args:
            instrument_token (str): The tick's `instrument_token`, such as "5:565899", or the subscription spelling "MCX_COMM:565899".

        Returns:
            FeedKey | None: The key, or None for a malformed token or an unknown segment.
        """
        segment, _, security_id = str(instrument_token).partition(":")
        if not security_id:
            return None
        code = self.SEGMENT_NAMES.get(segment)
        if code is None:
            try:
                code = int(segment)
            except ValueError:
                return None
        segments = self._segments.get(code)
        if segments is None:
            return None
        return FeedKey(security_id.strip(), segments)

    def tick_spelling(self, subscription_token):
        """
        A Dhan subscription token as ticks carry it: the segment by number rather than name.

        Args:
            subscription_token (str): A member of `subscriptions_dhan`, such as "MCX_COMM:565899".

        Returns:
            str | None: The tick's spelling, such as "5:565899", or None for an unknown segment.
        """
        segment, _, security_id = str(subscription_token).partition(":")
        if not security_id:
            return None
        if segment in self.SEGMENT_NAMES:
            return f"{self.SEGMENT_NAMES[segment]}:{security_id.strip()}"
        return f"{segment}:{security_id.strip()}" if segment.isdigit() else None
