"""The parameters of `DELETE /api/orders/cancel`, validated."""

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
