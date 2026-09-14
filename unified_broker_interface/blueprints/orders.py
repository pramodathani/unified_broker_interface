"""
`/api/orders`: today's orders and trades across every broker.

| Route | Does |
| --- | --- |
| `GET /details` | Every broker's orders, from `unified:orders:orders`, kept by `bin/unified/orders` every half second |
| `GET /trades` | Every broker's trades, from `unified:orders:trades`, kept by `bin/unified/trades` every half second |

Nothing here asks a broker, and nothing here places, modifies or cancels an order.
"""

from flask import jsonify

from unified_broker_interface.blueprints.base import BaseBlueprint, authenticated
from unified_broker_interface.utilities.unified_documents import read_document

class OrdersBlueprint(BaseBlueprint):
    """The `/api/orders` routes, which answer from documents the `bin/unified/` scripts keep in Redis."""

    name = 'orders'
    routes = [
        ('/details', 'details', ['GET']),
        ('/trades', 'trades', ['GET']),
    ]

    @authenticated
    def details(self):
        """Answers today's orders at every broker, with how each broker's data was read.

        See `utilities/unified_documents.py` for when the document is not served.

        Returns:
            tuple: The Flask JSON response (flask.Response) and its HTTP status (int).
        """
        body, status = read_document(self.cache, 'unified:orders:orders', 30, 'orders')
        return jsonify(body), status

    @authenticated
    def trades(self):
        """Answers today's trades at every broker, with how each broker's data was read.

        See `utilities/unified_documents.py` for when the document is not served.

        Returns:
            tuple: The Flask JSON response (flask.Response) and its HTTP status (int).
        """
        body, status = read_document(self.cache, 'unified:orders:trades', 30, 'trades')
        return jsonify(body), status

orders_bp = OrdersBlueprint().blueprint
