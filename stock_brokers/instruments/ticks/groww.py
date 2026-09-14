"""
Groww ticks.

Groww names an instrument as `EXCHANGE|SEGMENT|EXCHANGE_TOKEN` - `NSE|CASH|2885`, `NSE|FNO|35001` - and
stores the bare exchange token, which collides across segments, so the exchange and segment narrow
the search. Its feed publishes NSE and BSE cash and derivatives only; Groww is still the authority on
MCX lot sizes, from its instrument file, whether or not its feed streams MCX.

Nothing Groww streams is stored yet - its raw tick table is empty - so the broker stays unverified until
a live session, and two things are read conservatively:

- `close` is not taken as the previous close. The protobuf field is named only `close`, and at two of
  the brokers measured a field of that name turns into the day's own close after the session. The
  previous close comes from an earlier owner's tick the same day instead.
- Quantities are taken to be units, which is what NSE and BSE report and what every broker measured
  on those exchanges sends.

The book carries no order counts, and the feed sends no last trade time or last quantity; those
fields are null rather than guessed.
"""

from stock_brokers.instruments.ticks.base import CLOSE_NEVER, FeedKey, TickNormalizer, family_segments

class GrowwTickNormalizer(TickNormalizer):
    """
    Normalizes Groww ticks.
    """

    BROKER_NAME = "groww"

    # Groww segment to family. Indices arrive on the cash segment.
    SEGMENTS = {"CASH": "cash_or_index", "FNO": "derivative", "COMMODITY": "derivative"}
    EXCHANGES = {"NSE": "nse", "BSE": "bse", "MCX": "mcx"}

    CLOSE_POLICY = {"nse": CLOSE_NEVER, "bse": CLOSE_NEVER}

    TRUSTS_LAST_TRADE_TIME = False

    def __init__(self):
        self._segments = {(prefix, segment): family_segments([exchange], family)
                          for prefix, exchange in self.EXCHANGES.items()
                          for segment, family in self.SEGMENTS.items()}

    def feed_key(self, instrument_token):
        """
        The broker token and segments for a Groww `EXCHANGE|SEGMENT|EXCHANGE_TOKEN`.

        Args:
            instrument_token (str): The tick's `instrument_token`, such as "NSE|CASH|2885".

        Returns:
            FeedKey | None: The key, or None for a malformed token or an unknown exchange or segment.
        """
        parts = [part.strip() for part in str(instrument_token).split("|")]
        if len(parts) != 3 or not parts[2]:
            return None
        segments = self._segments.get((parts[0].upper(), parts[1].upper()))
        if segments is None:
            return None
        return FeedKey(parts[2], segments)
