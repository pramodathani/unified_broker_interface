"""
Wisdom Capital ticks, from Symphony's XTS platform.

XTS names an instrument by exchange segment number and exchange instrument id - `1:2885` - and
stores the bare instrument id, which collides across segments (the same id is an NSE equity and an
MCX future), so the segment narrows the search. The numbers are the ones
`stock_brokers/instruments/historical/wisdom_capital.py` downloads candles with, repeated here rather
than imported because that module pulls in the API client; indices sit under the cash segments.

What XTS's values mean, as measured against the stored ticks of 2026-09-12 and 2026-09-13:

- `Close` is not the previous close: RELIANCE read `Close` 1270.1 with a last price of 1270.1 in every
  snapshot, where the previous close was 1257.5. The previous close therefore comes only from an
  earlier owner's tick the same day, until a live session shows XTS carries it somewhere else.
- The last trade and exchange times, corrected from XTS's 1980 epoch in the market feed, are true
  instants: RELIANCE's last mock trade read 21:02:12, the second Flattrade's feed time shows.
- Quantities on NSE and BSE are units (RELIANCE's mock volume 1150, the same as Flattrade's). MCX
  quantities are taken to be lots, as at every broker measured, which a live session checks.
"""

from stock_brokers.instruments.ticks.base import CLOSE_NEVER, QUANTITY_FIELDS, FeedKey, TickNormalizer, family_segments

class WisdomCapitalTickNormalizer(TickNormalizer):
    """
    Normalizes Wisdom Capital ticks.
    """

    BROKER_NAME = "wisdom_capital"

    # XTS exchange segment number to (exchanges, family).
    SEGMENT_NUMBERS = {
        1: (("nse",), "cash_or_index"),     # NSECM
        2: (("nse",), "derivative"),        # NSEFO
        3: (("nse",), "derivative"),        # NSECD
        4: (("nse",), "derivative"),        # NSECO
        11: (("bse",), "cash_or_index"),    # BSECM
        12: (("bse",), "derivative"),       # BSEFO
        13: (("bse",), "derivative"),       # BSECD
        21: (("ncdex",), "derivative"),     # NCDEX
        51: (("mcx",), "derivative"),       # MCXFO
    }

    # XTS also spells the segments by name in some payloads.
    SEGMENT_NAMES = {"NSECM": 1, "NSEFO": 2, "NSECD": 3, "NSECO": 4, "BSECM": 11, "BSEFO": 12,
                     "BSECD": 13, "NCDEX": 21, "MCXFO": 51}

    LOT_FIELDS = {"mcx": frozenset(QUANTITY_FIELDS), "ncdex": frozenset(QUANTITY_FIELDS)}

    CLOSE_POLICY = {exchange: CLOSE_NEVER for exchange in ("nse", "bse", "mcx", "ncdex")}

    def __init__(self):
        self._segments = {number: family_segments(exchanges, family)
                          for number, (exchanges, family) in self.SEGMENT_NUMBERS.items()}

    def feed_key(self, instrument_token):
        """
        The broker token and segments for an XTS `SEGMENT:INSTRUMENT_ID`.

        Args:
            instrument_token (str): The tick's `instrument_token`, such as "1:2885" or "NSECM:2885".

        Returns:
            FeedKey | None: The key, or None for a malformed token or an unknown segment.
        """
        segment, _, instrument_id = str(instrument_token).partition(":")
        segment = segment.strip().upper()
        number = self.SEGMENT_NAMES.get(segment)
        if number is None:
            try:
                number = int(segment)
            except ValueError:
                return None
        segments = self._segments.get(number)
        if segments is None or not instrument_id.strip():
            return None
        return FeedKey(instrument_id.strip(), segments)

    def tick_spelling(self, subscription_token):
        """
        An XTS subscription token as ticks carry it: the segment by number.

        Args:
            subscription_token (str): A member of `subscriptions_wisdom_capital`, such as "1:2885".

        Returns:
            str | None: The tick's spelling, or None for an unknown segment.
        """
        segment, _, instrument_id = str(subscription_token).partition(":")
        number = self.SEGMENT_NAMES.get(segment.strip().upper())
        if number is None:
            return subscription_token if segment.strip().isdigit() and instrument_id.strip() else None
        return f"{number}:{instrument_id.strip()}"
