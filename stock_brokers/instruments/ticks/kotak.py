"""
Kotak Neo ticks.

Kotak names an instrument as `exchange_segment|token` in its own segment vocabulary - `nse_cm`,
`nse_fo`, `mcx_fo` - and stores the bare token, which collides across segments, so the segment
narrows the search.

What Kotak's values mean, as measured on Kotak's HSM feed (`wss://mlhsm.kotaksecurities.com`) against
Zerodha's ticks received at the same moment during the session of 2026-09-15:

- `close` is the previous session's close: TCS read 2200.80, HDFCBANK 708.25 and CRUDEOIL SEP 9717.0,
  all Zerodha's figures, while their last prices moved.
- On MCX every quantity - last quantity, volume, total buy and sell quantity, open interest and every
  order book quantity - is lots times Kotak's own lot size. GOLD OCT (Kotak's lot 1) read volume 562 and
  open interest 9474, Zerodha's lots exactly; CRUDEOIL SEP (Kotak's lot 100) read 276900 and 1598900
  against Zerodha's 2769 and 15989; NATURALGAS SEP (Kotak's lot 1250) read 4943750 and 49037500 against
  3955 and 39230. So each is divided by Kotak's lot size and multiplied by the authoritative one.
- On NSE and BSE quantities are units, as at Zerodha.
- Both times are true instants: the last trade time and the exchange timestamp matched Zerodha's to the
  second on TCS, HDFCBANK, CRUDEOIL, NATURALGAS and GOLD.

The earlier `sfeed` feed, measured on the weekend snapshots of 2026-09-12 and 2026-09-13, sent a date
with no time and scaled only the MCX last quantity; `bin/kotak/instruments/websocket_quotes` no longer uses it.
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

    BROKER_LOT_FIELDS = {"mcx": frozenset(QUANTITY_FIELDS)}

    CLOSE_POLICY = {"nse": CLOSE_ALWAYS, "bse": CLOSE_ALWAYS, "mcx": CLOSE_ALWAYS}

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
