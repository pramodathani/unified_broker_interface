"""
INDmoney (INDstocks) ticks.

INDstocks names an instrument as `SEGMENT:TOKEN` - `NSE:2885`, `NFO:35001`, `NIDX:40000001` - with
equity on `NSE` and `BSE`, derivatives on `NFO` and `BFO` and indices on `NIDX` and `BIDX`, and stores
the bare token. No INDstocks token collided across segments on 2026-09-13, but the segment still
narrows the search so that one never silently does.

What INDmoney's values mean, as measured on the feed's `full` mode against Zerodha's ticks received at
the same moment during the session of 2026-09-15, on TCS, INFY, ICICIBANK, RELIANCE and HDFCBANK:

- `close` is not the previous close but the last price: HDFCBANK read 722.25 as both, where the
  previous close was 708.25. It is never used; the previous close comes from an earlier owner's tick the
  same day instead.
- Prices are rupees: last price, open, high and low matched Zerodha's.
- Quantities are units: INFY and ICICIBANK volumes matched Zerodha's exactly.
- Both times are true instants: the last trade time matched Zerodha's to within three seconds and the
  exchange timestamp to within two, and ticks arrived 0.8 seconds after it.

The feed sends no last quantity, average price or order book quantities, and INDstocks streams no MCX.
"""

from stock_brokers.instruments.ticks.base import CLOSE_NEVER, FeedKey, TickNormalizer, family_segments

class IndmoneyTickNormalizer(TickNormalizer):
    """
    Normalizes INDmoney ticks.
    """

    BROKER_NAME = "indmoney"

    # INDstocks segment to (exchanges, family).
    SEGMENTS = {
        "NSE": (("nse",), "cash"),
        "BSE": (("bse",), "cash"),
        "NFO": (("nse",), "derivative"),
        "BFO": (("bse",), "derivative"),
        "NIDX": (("nse",), "index"),
        "BIDX": (("bse",), "index"),
    }

    CLOSE_POLICY = {"nse": CLOSE_NEVER, "bse": CLOSE_NEVER}

    def __init__(self):
        self._segments = {name: family_segments(exchanges, family)
                          for name, (exchanges, family) in self.SEGMENTS.items()}

    def feed_key(self, instrument_token):
        """
        The broker token and segments for an INDstocks `SEGMENT:TOKEN`.

        Args:
            instrument_token (str): The tick's `instrument_token`, such as "NSE:2885".

        Returns:
            FeedKey | None: The key, or None for a bare token the feed could not place, or an unknown segment.
        """
        segment, _, token = str(instrument_token).partition(":")
        segments = self._segments.get(segment.strip().upper())
        if segments is None or not token.strip():
            return None
        return FeedKey(token.strip(), segments)
