"""
`/api/orders`: today's orders and trades across every broker, and placing, modifying and cancelling orders.

| Route | Does |
| --- | --- |
| `GET /details` | Every broker's orders, from `unified:orders:orders`, kept by `bin/unified/orders` every half second |
| `GET /trades` | Every broker's trades, from `unified:orders:trades`, kept by `bin/unified/trades` every half second |
| `POST /place` | Places an order at the broker the API chooses |
| `PUT /modify` | Modifies a pending or open order, named by `broker` and `order_id` |
| `DELETE /cancel` | Cancels a pending or open order, named by `broker` and `order_id` |

Orders are answered in the project's order contract, and written in it too. The writes take a JSON body, or
query parameters, and `dry_run` builds a write without sending it. The write routes only shape responses - the
work is in `utilities/broker_orders/`.
"""

import threading

from flask import jsonify, request

from stock_brokers.instruments.mapping.utilities.cache import MappingCache
from unified_broker_interface.blueprints.base import BaseBlueprint, authenticated
from unified_broker_interface.blueprints.instruments import answers_request_errors
from unified_broker_interface.utilities.broker_funds.utilities.service import read_funds
from unified_broker_interface.utilities.broker_orders.utilities.write_service import OrderWriteService
from unified_broker_interface.utilities.broker_quotes.utilities.service import QuoteService
from unified_broker_interface.utilities.instrument_catalogue import InstrumentCatalogue
from unified_broker_interface.utilities.unified_documents import read_document

class OrdersBlueprint(BaseBlueprint):
    name = 'orders'
    routes = [
        ('/details', 'details', ['GET']),
        ('/trades', 'trades', ['GET']),
        ('/place', 'place', ['POST']),
        ('/modify', 'modify', ['PUT']),
        ('/cancel', 'cancel', ['DELETE']),
    ]

    def __init__(self):
        super().__init__()
        self._writes_lock = threading.Lock()
        self._writes = None

    def _write_service(self):
        """
        This worker's order-write service, built on first use, so the application starts without touching Postgres.
        """
        with self._writes_lock:
            if self._writes is None:
                mapping_cache = MappingCache()
                self._writes = OrderWriteService(
                    self.cache, mapping_cache, InstrumentCatalogue(mapping_cache), QuoteService(mapping_cache, self.cache),
                    lambda broker: read_funds(broker)["summary"]["available_balance"])
        return self._writes

    def _body(self):
        """
        A write's fields: the JSON body, with any query parameters beneath it.
        """
        body = dict(request.args)
        body.update(request.get_json(silent=True) or {})
        return body

    @authenticated
    def details(self):
        """
        Today's orders at every broker, with how each broker's data was read. See `utilities/unified_documents.py` for
        when the document is not served.
        """
        body, status = read_document(self.cache, 'unified:orders:orders', 30, 'orders')
        return jsonify(body), status

    @authenticated
    def trades(self):
        """
        Today's trades at every broker, with how each broker's data was read. See `utilities/unified_documents.py` for
        when the document is not served.
        """
        body, status = read_document(self.cache, 'unified:orders:trades', 30, 'trades')
        return jsonify(body), status

    @authenticated
    @answers_request_errors
    def place(self):
        """
        Place an order at the broker the API chooses; `dry_run` returns the call without sending it.

        Answers `200` accepted, `422` rejected, `504` outcome unknown, `503` when no broker can take the order,
        `429` when the chosen broker is at its order limit and `400` for an order that is not valid.
        """
        writes = self._write_service()
        document, status = writes.place(self._body())
        return jsonify(document), status

    @authenticated
    @answers_request_errors
    def modify(self):
        """
        Modify a pending or open order; `dry_run` returns the call without sending it.

        Answers as `place` does, and `404` for an order not in the broker's book or `409` for one already closed.
        """
        writes = self._write_service()
        document, status = writes.modify(self._body())
        return jsonify(document), status

    @authenticated
    @answers_request_errors
    def cancel(self):
        """
        Cancel a pending or open order; `dry_run` returns the call without sending it.

        Answers as `modify` does.
        """
        writes = self._write_service()
        document, status = writes.cancel(self._body())
        return jsonify(document), status

orders_bp = OrdersBlueprint().blueprint
