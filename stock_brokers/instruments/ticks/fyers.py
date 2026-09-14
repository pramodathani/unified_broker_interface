"""
Fyers ticks.

A Fyers tick names its instrument by symbol - `NSE:SBIN-EQ`, `MCX:CRUDEOIL26SEPFUT` - rather than by
token. unified.broker_mappings stores that symbol as Fyers's order symbol beside its numeric
token, so the resolver translates one to the other before searching. The symbol's prefix gives the
exchange and its shape the kind: `-INDEX` is an index, a symbol ending in FUT, CE or PE a derivative on
NSE and BSE, anything else there cash; everything on MCX is a derivative.

Nothing Fyers streams is stored yet - its raw tick table is empty - so every fact below is from its
protocol rather than from a measurement, and the broker stays unverified until a live session:

- `prev_close_price` is named for what it is, and is taken as the previous close at every hour.
- MCX quantities are taken to be lots, as at every broker measured.
- The last traded and exchange feed times are epochs.

Currency derivatives are left out. Fyers scales prices by a precision and multiplier per instrument
that arrive with the subscription, and the market feed does not read them yet, so it divides every
price by 100 - right for two-decimal instruments, a hundred times wrong for four-decimal currency
pairs. Refusing those instruments writes nothing rather than something wrong; they return once the
feed reads its scale.
"""

from stock_brokers.instruments.ticks.base import CLOSE_ALWAYS, QUANTITY_FIELDS, FeedKey, TickNormalizer, family_segments

class FyersTickNormalizer(TickNormalizer):
    """
    Normalizes Fyers ticks.
    """

    BROKER_NAME = "fyers"

    EXCHANGES = {"NSE": "nse", "BSE": "bse", "MCX": "mcx"}

    DERIVATIVE_SUFFIXES = ("FUT", "CE", "PE")

    LOT_FIELDS = {"mcx": frozenset(QUANTITY_FIELDS)}

    CLOSE_POLICY = {"nse": CLOSE_ALWAYS, "bse": CLOSE_ALWAYS, "mcx": CLOSE_ALWAYS}

    def __init__(self):
        self._segments = {}
        for prefix, exchange in self.EXCHANGES.items():
            for family in ("cash", "index", "derivative"):
                segments = family_segments([exchange], family)
                if family == "derivative":
                    segments = tuple(segment for segment in segments if "_currenc" not in segment)
                self._segments[(prefix, family)] = segments

    def feed_key(self, instrument_token):
        """
        The order symbol and segments for a Fyers symbol.

        Args:
            instrument_token (str): The tick's `instrument_token`, a Fyers symbol such as "NSE:SBIN-EQ".

        Returns:
            FeedKey | None: The key, carrying the symbol as the order symbol, or None for an unknown exchange.
        """
        symbol = str(instrument_token).strip()
        prefix, _, name = symbol.partition(":")
        prefix = prefix.upper()
        if prefix not in self.EXCHANGES or not name:
            return None
        if prefix == "MCX" or name.upper().endswith(self.DERIVATIVE_SUFFIXES):
            family = "derivative"
        elif name.upper().endswith("-INDEX"):
            family = "index"
        else:
            family = "cash"
        return FeedKey(None, self._segments[(prefix, family)], symbol)
