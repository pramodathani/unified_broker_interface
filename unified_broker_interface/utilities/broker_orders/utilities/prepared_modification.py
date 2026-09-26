"""One modification checked and built for the broker whose order book holds the order, before it is sent."""

import time


class PreparedModification:
    """A modification that has passed every check and has a built request, but has not been sent.

    `PUT /api/orders/modify` builds one for its single order, and for each order of a list. Either answers from it the same way, by showing the request for a dry run or by sending it.

    Attributes:
        broker_orders (BrokerOrders): The order class of the broker holding the order.
        broker_name (str): That broker's name.
        order_id (str): The broker's order id.
        stored_order (StoredOrder): The order as the broker's order book in Redis holds it.
        instrument_id (str | None): The instrument found for the order in today's catalogue, or None when none was found.
        broker_request (BrokerRequest): The modify request built for the broker, not yet sent.
    """

    def __init__(self, broker_orders, order_id, stored_order, instrument_id, broker_request):
        """Builds the prepared modification.

        Args:
            broker_orders (BrokerOrders): The order class of the broker holding the order.
            order_id (str): The broker's order id.
            stored_order (StoredOrder): The order as the broker's order book in Redis holds it.
            instrument_id (str | None): The instrument found for the order, or None.
            broker_request (BrokerRequest): The modify request built for the broker.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = broker_orders
        self.broker_name = broker_orders.BROKER_NAME
        self.order_id = order_id
        self.stored_order = stored_order
        self.instrument_id = instrument_id
        self.broker_request = broker_request

    def dry_run_answer(self, started_at):
        """The answer for a dry run: the request that would have been sent.

        Args:
            started_at (float): `time.perf_counter()` when the HTTP request arrived.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int), always 200.
        """
        preparation_milliseconds = (time.perf_counter() - started_at) * 1000
        return {
            'broker': self.broker_name,
            'order_id': self.order_id,
            'instrument_id': self.instrument_id,
            'status_before_modify': self.stored_order.status,
            'dry_run': True,
            'request': self.broker_request.shown(),
            'timing_ms': {
                'preparation': round(preparation_milliseconds, 3),
            },
        }, 200

    def send(self, started_at):
        """Sends the modification to the broker once, without retrying, and answers with what the broker said.

        Args:
            started_at (float): `time.perf_counter()` when the HTTP request arrived.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int), which is 200 when the broker accepted the modification, 422 when it refused it and 504 when the outcome is unknown.
        """
        answer = self.broker_orders.send_modify(self.broker_request)
        preparation_milliseconds = (answer.sent_at - started_at) * 1000
        return {
            'broker': self.broker_name,
            'order_id': self.order_id,
            'instrument_id': self.instrument_id,
            'status_before_modify': self.stored_order.status,
            'outcome': answer.outcome,
            'status_message': answer.status_message,
            'broker_response': answer.response_body,
            'timing_ms': {
                'preparation': round(preparation_milliseconds, 3),
                'broker': answer.broker_milliseconds(),
            },
        }, answer.http_status()
