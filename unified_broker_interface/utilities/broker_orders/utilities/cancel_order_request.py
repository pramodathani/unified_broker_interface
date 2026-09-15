"""The parameters of `DELETE /api/orders/cancel`, validated."""

import re

from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    OrderRequest,
)


class CancelOrderRequest(OrderRequest):
    """One cancel as the caller asked for it, read from the JSON body first and the query string second.

    Attributes:
        order_id (str): The broker's order id.
        broker (str | None): The broker the caller named, lower-cased, or None.
        dry_run (bool): Whether to answer with the request instead of sending it.
    """

    def __init__(self, body, query_arguments, broker_names):
        """Validates the cancel's parameters.

        Args:
            body (object): The decoded JSON body, or None when there is none or it is not JSON.
            query_arguments (werkzeug.datastructures.MultiDict): The query string arguments.
            broker_names (list): Every broker's name, for checking `broker`.

        Returns:
            None: This method returns nothing.

        Raises:
            InvalidOrderError: When the body is not an object, or `order_id`, `broker` or `dry_run` is invalid.
        """
        if body is None:
            body = {}
        if not isinstance(body, dict):
            raise InvalidOrderError('the request body must be a JSON object')
        self.order_id = self.parse_order_id(body, query_arguments)
        self.broker = self.parse_broker(body, query_arguments, broker_names)
        raw_dry_run = body.get('dry_run')
        if raw_dry_run is None:
            raw_dry_run = query_arguments.get('dry_run')
        self.dry_run = self.parse_flag('dry_run', raw_dry_run)

    def parse_order_id(self, body, query_arguments):
        """Reads the order id.

        Args:
            body (dict): The request body.
            query_arguments (werkzeug.datastructures.MultiDict): The query string arguments.

        Returns:
            str: The order id with surrounding spaces removed.

        Raises:
            InvalidOrderError: When the order id is missing or is not 1 to 64 letters, digits, hyphens or underscores.
        """
        order_id = body.get('order_id')
        if order_id is None:
            order_id = query_arguments.get('order_id')
        if order_id is None or order_id == '':
            raise InvalidOrderError('order_id is required')
        if isinstance(order_id, int) and not isinstance(order_id, bool):
            order_id = str(order_id)
        if isinstance(order_id, str):
            order_id = order_id.strip()
        if not isinstance(order_id, str) or not re.fullmatch(
            r'[A-Za-z0-9_-]{1,64}',
            order_id,
        ):
            message = (
                'order_id must be 1 to 64 letters, digits, hyphens or underscores'
            )
            raise InvalidOrderError(message)
        return order_id

    def parse_broker(self, body, query_arguments, broker_names):
        """Reads the optional broker name.

        Args:
            body (dict): The request body.
            query_arguments (werkzeug.datastructures.MultiDict): The query string arguments.
            broker_names (list): Every broker's name.

        Returns:
            str | None: The broker name, lower-cased, or None when not given.

        Raises:
            InvalidOrderError: When the name is not one of the brokers.
        """
        requested_broker = body.get('broker')
        if requested_broker is None:
            requested_broker = query_arguments.get('broker')
        if requested_broker is None or requested_broker == '':
            return None
        requested_broker = str(requested_broker).strip().lower()
        if requested_broker not in broker_names:
            message = 'broker must be one of ' + ', '.join(broker_names)
            raise InvalidOrderError(message)
        return requested_broker
