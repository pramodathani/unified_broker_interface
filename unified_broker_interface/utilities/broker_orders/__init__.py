"""
Today's orders and trades read live from each broker's REST API, for `/api/orders/details` and
`/api/orders/trades`.

One module per broker calls that broker's order book and trade book and turns each row into the project's
order contract - a normalized order update, built by `empty_order_update` and mapped onto the shared
vocabulary - or into a trade in the same vocabulary. `base.py` defines what a broker module provides and the
trade's shape; `utilities/` holds the service that asks every broker at once and resolves each row to its
unified.instruments id.

**None of the field names inside a populated row has been read back live.** No account had an order or a
trade when this was written, so each module follows its broker's published schema, or the field names the
broker's order update messages carry where that payload is the order-book row, and only the empty answers
were seen.
"""
