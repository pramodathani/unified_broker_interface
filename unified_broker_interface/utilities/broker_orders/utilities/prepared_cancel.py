"""One cancel checked and built for the broker whose order book holds the order, before it is sent."""

import time


class PreparedCancel:
    """A cancel that has passed every check and has a built request, but has not been sent.

    `DELETE /api/orders/cancel` builds one for its single order, and for each order of a list. Either answers from it the same way, by showing the request for a dry run or by sending it.

    Attributes:
        broker_orders (BrokerOrders): The order class of the broker holding the order.
        broker_name (str): That broker's name.
        order_id (str): The broker's order id.
        stored_order (StoredOrder): The order as the broker's order book in Redis holds it.
        broker_request (BrokerRequest): The cancel request built for the broker, not yet sent.
        engine_command (str | None): The command that hands this cancel to the order engine, when the engine's parent owns the order, or None for an order placed elsewhere.
        engine_arguments (dict | None): What the engine is handed to make the cancel, or None when the engine does not own the order.
    """

    def __init__(self, broker_orders, order_id, stored_order, broker_request):
        """Builds the prepared cancel.

        Args:
            broker_orders (BrokerOrders): The order class of the broker holding the order.
            order_id (str): The broker's order id.
            stored_order (StoredOrder): The order as the broker's order book in Redis holds it.
            broker_request (BrokerRequest): The cancel request built for the broker.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = broker_orders
        self.broker_name = broker_orders.BROKER_NAME
        self.order_id = order_id
        self.stored_order = stored_order
        self.broker_request = broker_request
        self.engine_command = None
        self.engine_arguments = None

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
            'status_before_cancel': self.stored_order.status,
            'dry_run': True,
            'request': self.broker_request.shown(),
            'timing_ms': {
                'preparation': round(preparation_milliseconds, 3),
            },
        }, 200

    def send(self, started_at):
        """Sends the cancel to the broker once, without retrying, and answers with what the broker said.

        Args:
            started_at (float): `time.perf_counter()` when the HTTP request arrived.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int), which is 200 when the broker accepted the cancel, 422 when it refused it and 504 when the outcome is unknown.
        """
        answer = self.broker_orders.send_cancel(self.broker_request)
        preparation_milliseconds = (answer.sent_at - started_at) * 1000
        return {
            'broker': self.broker_name,
            'order_id': self.order_id,
            'status_before_cancel': self.stored_order.status,
            'outcome': answer.outcome,
            'status_message': answer.status_message,
            'broker_response': answer.response_body,
            'timing_ms': {
                'preparation': round(preparation_milliseconds, 3),
                'broker': answer.broker_milliseconds(),
            },
        }, answer.http_status()
