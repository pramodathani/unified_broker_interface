"""
Fyers positions, from `GET https://api-t1.fyers.in/api/v3/positions`.

The body has no `data` envelope, so the API client passes it through whole; its `netPositions` is a list with
one row per position. Following Fyers' published v3 schema, a row names its instrument by `fyToken`, which
unified.broker_mappings stores, and by `symbol`, `NSE:NIFTY26SEPFUT`, whose prefix is the exchange;
`segment` is 10 for cash, 11 for equity derivatives, 12 for currency and 20 for commodities. Beside them are
`productType`, the signed `netQty`, `buyQty` and `buyVal`, `sellQty` and `sellVal`, `realized_profit`,
`unrealized_profit` and `ltp`. Fyers reports no day basis.

**Not read back live.** Every request on 2026-09-13 met Fyers' request limit, which its candle downloader was
using up. Refusals are read as for funds and share its pause; see `broker_funds/fyers.py`.
"""

from stock_brokers.api.fyers import FyersAPIException
from unified_broker_interface.utilities.broker_funds import fyers as fyers_refusals
from unified_broker_interface.utilities.broker_positions.base import BrokerPositionsSource, PositionsUnavailable, position

POSITIONS_URL = "https://api-t1.fyers.in/api/v3/positions"

# Fyers' segment codes to the kind of instrument traded there.
SEGMENT_KINDS = {"10": "cash", "11": "derivative", "12": "currency", "20": "commodity"}

class FyersPositionsSource(BrokerPositionsSource):
    """
    Reads Fyers positions.
    """

    BROKER_NAME = "fyers"

    def fetch(self, client):
        fyers_refusals.paused("positions")
        try:
            data = (client.get(url=POSITIONS_URL, timeout=self.TIMEOUT_SECONDS) or {}).get("data")
        except FyersAPIException as exception:
            fyers_refusals.note_refusal(exception, "positions")
            raise
        if not isinstance(data, dict):
            raise PositionsUnavailable(f"Fyers answered the positions request without positions: {str(data)[:200]}")
        if data.get("s") not in (None, "ok"):
            # Fyers can refuse inside a 200; raised as the API client would, so the session codes are seen.
            exception = FyersAPIException(code=data.get("code"), message=data.get("message"))
            fyers_refusals.note_refusal(exception, "positions")
            raise exception
        return {"net": data.get("netPositions") or [], "day": None}

    def normalize(self, data):
        positions = []
        for row in data:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "")
            prefix, _, trading_symbol = symbol.partition(":")
            positions.append(position(
                broker_token=row.get("fyToken"), exchange=prefix.lower() or None,
                kind=SEGMENT_KINDS.get(str(row.get("segment"))), symbol=trading_symbol or symbol,
                product_code=row.get("productType"), quantity=row.get("netQty"),
                buy_quantity=row.get("buyQty"), buy_value=row.get("buyVal"),
                sell_quantity=row.get("sellQty"), sell_value=row.get("sellVal"),
                realized=row.get("realized_profit"), unrealized=row.get("unrealized_profit"),
                last_price=row.get("ltp"),
            ))
        return positions

    def is_authentication_error(self, exception):
        return fyers_refusals.is_authentication_error(exception)
