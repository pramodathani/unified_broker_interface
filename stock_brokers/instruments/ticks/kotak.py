"""
Kotak Neo ticks.

Kotak names an instrument as `exchange_segment|token` in its own segment vocabulary - `nse_cm`,
`nse_fo`, `mcx_fo` - and stores the bare token, which collides across segments, so the segment
narrows the search.

What Kotak's values mean, as measured on Kotak's SFeed market feed (`wss://sfeed.kotaksecurities.com/apifeed`) against
Zerodha's ticks received within a second during the session of 2026-10-28:

- `close` is the previous session's close: CRUDEOIL NOV read 9498.0, NATURALGAS NOV 288.4, GOLD DEC 144138.0,
  RELIANCE 1196.2 and TCS 2496.9, all Zerodha's figures, while their last prices moved.
- On MCX every quantity - last quantity, volume, total buy and sell quantity, open interest and every
  order book quantity - is in lots, as at Zerodha, whatever Kotak's own lot size: CRUDEOIL NOV (Kotak's lot 100)
  read volume 3528 and open interest 13801, NATURALGAS NOV (Kotak's lot 1250) 9022 and 48182, and GOLD DEC
  (Kotak's lot 1) 531 and 15603, Zerodha's figures exactly. So each is multiplied by the authoritative lot size.
- On NSE and BSE quantities are units, as at Zerodha.
- Both times are true instants in Unix seconds: the last trade time and the exchange timestamp matched Zerodha's
  to the second on CRUDEOIL, NATURALGAS and GOLD.

Kotak's HSM feed (`wss://mlhsm.kotaksecurities.com`), which `bin/kotak/instruments/websocket_quotes` streamed from
until Kotak retired it in October 2026, sent every MCX quantity as lots times Kotak's own lot size instead, measured
against Zerodha on 2026-09-15: CRUDEOIL SEP read 276900 for Zerodha's 2769.
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

    LOT_FIELDS = {"mcx": frozenset(QUANTITY_FIELDS)}

    CLOSE_POLICY = {"nse": CLOSE_ALWAYS, "bse": CLOSE_ALWAYS, "mcx": CLOSE_ALWAYS}

    def __init__(self):
        """
        Build the lookup from each Kotak exchange segment to the canonical segments it can hold.

        The table is worked out once here from `EXCHANGE_SEGMENTS`, so `feed_key` only has to look a tick's exchange segment up rather than recompute its segments on every call.
        """
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
