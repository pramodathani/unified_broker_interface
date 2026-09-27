"""A change to an order the order engine is still holding, as `PUT /api/orders/modify` takes it with `parent_id`."""

from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    OrderRequest,
)

OTHER_FIELD_NAMES = [
    'order_id',
    'broker',
    'disclosed_quantity',
    'trigger_price',
    'order_type',
    'validity',
]


class HeldOrderChange(OrderRequest):
    """One change to a held order, such as a virtual limit order that has not yet been sent to a broker.

    A held order has no broker order id yet, so it is named by the `parent_id` the place route answered with. Only its `price` and `quantity` can change, because those are the only terms the virtual order book holds it by; `dry_run` checks the change without making it. `dry_run` is read from the body first and the query string second, as the rest of the route reads it.

    Attributes:
        parent_id (str): The engine's parent id.
        price (decimal.Decimal | None): The new limit price, or None when it is not changed.
        quantity (int | None): The new quantity in units, or None when it is not changed.
        dry_run (bool): Whether to check the change without making it.
    """

    def __init__(self, body, query_arguments):
        """Validates the change.

        Args:
            body (object): The decoded JSON body, or one entry of the `orders` list.
            query_arguments (werkzeug.datastructures.MultiDict): The query string arguments.

        Returns:
            None: This method returns nothing.

        Raises:
            InvalidOrderError: When the body is not an object, `parent_id` is missing, a field other than price and quantity is given, or neither is.
        """
        if not isinstance(body, dict):
            raise InvalidOrderError('the request body must be a JSON object')
        parent_id = body.get('parent_id')
        if not isinstance(parent_id, str) or not parent_id:
            raise InvalidOrderError('parent_id must name a parent')
        self.parent_id = parent_id
        for field_name in OTHER_FIELD_NAMES:
            if body.get(field_name) is not None:
                raise InvalidOrderError(
                    f'an order named by parent_id is still held, so only its price and quantity can change, not {field_name}'
                )
        raw_dry_run = body.get('dry_run')
        if raw_dry_run is None:
            raw_dry_run = query_arguments.get('dry_run')
        self.dry_run = self.parse_flag('dry_run', raw_dry_run)
        self.quantity = self.parse_whole_number(body, 'quantity', 1)
        self.price = self.parse_price(body, 'price')
        if self.quantity is None and self.price is None:
            raise InvalidOrderError('give price or quantity to change')

    def command_arguments(self):
        """The arguments of the engine's `modify_held` command.

        Returns:
            dict: `parent_id`, `price` as text or None, `quantity` and `dry_run`.
        """
        price = None
        if self.price is not None:
            price = str(self.price)
        return {
            'parent_id': self.parent_id,
            'price': price,
            'quantity': self.quantity,
            'dry_run': self.dry_run,
        }
