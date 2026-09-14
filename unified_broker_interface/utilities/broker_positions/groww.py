"""
Groww positions, from `GET https://api.groww.in/v1/positions/user`.

The API client unwraps Groww's `payload`, whose `positions` is a list; a flat account answers
`{"positions": []}`, measured on 2026-09-13. Following Groww's published schema, a row carries no token -
only `trading_symbol`, `exchange` and Groww's `segment`, `CASH`, `FNO` or `COMMODITY` - so a cash position is
resolved by its symbol and a derivative is left with Groww's own. Beside them are `product`, the signed
`quantity`, what was bought as `credit_quantity` at `credit_price` and sold as `debit_quantity` at
`debit_price`. Groww reports averages rather than values, and no profit and no price.
"""

from unified_broker_interface.utilities.broker_funds.base import number
from unified_broker_interface.utilities.broker_holdings.base import canonical_exchange
from unified_broker_interface.utilities.broker_holdings.groww import GrowwHoldingsSource
from unified_broker_interface.utilities.broker_positions.base import BrokerPositionsSource, PositionsUnavailable, position

POSITIONS_URL = "https://api.groww.in/v1/positions/user"

# Groww's segments to the kind of instrument traded there.
SEGMENT_KINDS = {"CASH": "cash", "FNO": "derivative", "COMMODITY": "commodity"}

class GrowwPositionsSource(BrokerPositionsSource):
    """
    Reads Groww positions.
    """

    BROKER_NAME = "groww"

    def fetch(self, client):
        data = (client.get(url=POSITIONS_URL, timeout=self.TIMEOUT_SECONDS) or {}).get("data")
        if not isinstance(data, dict) or not isinstance(data.get("positions", []), list):
            raise PositionsUnavailable(f"Groww answered the positions request without positions: {str(data)[:200]}")
        return {"net": data.get("positions") or [], "day": None}

    def normalize(self, data):
        positions = []
        for row in data:
            if not isinstance(row, dict):
                continue
            positions.append(position(
                exchange=canonical_exchange(row.get("exchange")) or str(row.get("exchange") or "").lower() or None,
                kind=SEGMENT_KINDS.get(str(row.get("segment") or "").upper()), symbol=row.get("trading_symbol"),
                product_code=row.get("product"), quantity=row.get("quantity"),
                buy_quantity=row.get("credit_quantity"),
                buy_value=number(row.get("credit_quantity")) * number(row.get("credit_price")),
                sell_quantity=row.get("debit_quantity"),
                sell_value=number(row.get("debit_quantity")) * number(row.get("debit_price")),
            ))
        return positions

    is_authentication_error = GrowwHoldingsSource.is_authentication_error
