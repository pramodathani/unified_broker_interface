"""
INDmoney (INDstocks) ticks.

INDstocks names an instrument as `SEGMENT:TOKEN` - `NSE:2885`, `NFO:35001`, `NIDX:40000001` - with
equity on `NSE` and `BSE`, derivatives on `NFO` and `BFO` and indices on `NIDX` and `BIDX`, and stores
the bare token. No INDstocks token collided across segments on 2026-09-13, but the segment still
narrows the search so that one never silently does.

Nothing INDmoney streams is stored yet - its raw tick table is empty - so the broker stays unverified
until a live session, and it is read conservatively:

- `close` is not taken as the previous close; the feed does not document which close it sends. The
  previous close comes from an earlier owner's tick the same day instead.
- Quantities are taken to be units, which is what NSE and BSE report.
- Prices are taken as the market feed publishes them. The feed treats INDstocks prices as rupees,
  which is documented for the last price only; a ratio of 100 against another broker's quote shows at once if
  that is wrong, and the correction is one constant in `bin/indmoney/quotes`.

The feed sends no last trade time, and INDstocks streams no MCX.
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

    TRUSTS_LAST_TRADE_TIME = False

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
