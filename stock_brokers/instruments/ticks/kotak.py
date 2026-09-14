"""
Kotak Neo ticks.

Kotak names an instrument as `exchange_segment|token` in its own segment vocabulary - `nse_cm`,
`nse_fo`, `mcx_fo` - and stores the bare token, which collides across segments, so the segment
narrows the search.

What Kotak's values mean, as measured against the stored ticks of 2026-09-12 and 2026-09-13:

- `close` is the previous session's close at every hour: RELIANCE read 1274.0 in every snapshot,
  as Zerodha's did, while its last price read Friday's 1257.5.
- On MCX, open interest is in lots - CRUDEOIL SEP 17552, GOLD OCT 9618, both Zerodha's figures.
- Kotak's MCX last quantity is not lots and not units but lots times Kotak's own lot size: CRUDEOIL
  read 100 (Kotak's lot 100), NATURALGAS 1250 and 2500 (Kotak's lot 1250), and GOLD 1 and 3 (Kotak's
  lot 1, where the contract's is 100). So it is divided by Kotak's lot size and multiplied by the
  authoritative one. The other MCX quantities are taken to be lots, which a live session checks.
- The feed's time fields are not usable yet: RELIANCE's last update read 2026-09-11 00:00 India time, a
  date without a time, and MCX sent none. Both are left out until a live session shows what they are.
"""

from stock_brokers.instruments.ticks.base import (CLOSE_ALWAYS, QUANTITY_FIELDS, FeedKey, TickNormalizer,
                                                  family_segments)

class KotakTickNormalizer(TickNormalizer):
    """
    Normalizes Kotak Neo ticks.
    """

    BROKER_NAME = "kotak"

    # Kotak exchange segment to (exchanges, family).
    EXCHANGE_SEGMENTS = {
        "nse_cm": (("nse",), "cash_or_index"),
        "bse_cm": (("bse",), "cash_or_index"),
        "nse_fo": (("nse",), "derivative"),
        "cde_fo": (("nse",), "derivative"),
        "nse_com": (("nse",), "derivative"),
        "bse_fo": (("bse",), "derivative"),
        "bse_cd": (("bse",), "derivative"),
        "bse_co": (("bse",), "derivative"),
        "mcx_fo": (("mcx",), "derivative"),
    }

    LOT_FIELDS = {"mcx": frozenset(QUANTITY_FIELDS) - {"last_quantity"}}
    BROKER_LOT_FIELDS = {"mcx": frozenset({"last_quantity"})}

    CLOSE_POLICY = {"nse": CLOSE_ALWAYS, "bse": CLOSE_ALWAYS, "mcx": CLOSE_ALWAYS}

    TRUSTS_LAST_TRADE_TIME = False
    TRUSTS_EXCHANGE_TIME = False

    def __init__(self):
        self._segments = {name: family_segments(exchanges, family)
                          for name, (exchanges, family) in self.EXCHANGE_SEGMENTS.items()}

    def feed_key(self, instrument_token):
        """
        The broker token and segments for a Kotak `exchange_segment|token`.

        Args:
            instrument_token (str): The tick's `instrument_token`, such as "nse_cm|2885".

        Returns:
            FeedKey | None: The key, or None for a malformed token or an unknown segment.
        """
        segment, _, token = str(instrument_token).partition("|")
        segments = self._segments.get(segment.strip().lower())
        if segments is None or not token.strip():
            return None
        return FeedKey(token.strip(), segments)
