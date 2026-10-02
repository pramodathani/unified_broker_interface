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
    'order_type',
    'validity',
]


class HeldOrderChange(OrderRequest):
    """One change to an order the engine has not yet sent to a broker: a held order, such as a virtual limit order, or one part of a plan.

    Such an order has no broker order id yet, so it is named by the `parent_id` the place route answered with, and a part of a plan also by its `part` path, as `GET /api/orders/parents` shows it. A held order can change only its `price` and `quantity`, because those are the only terms the virtual order book holds it by; a part can also change its `trigger_price`. `dry_run` checks the change without making it, and is read from the body first and the query string second, as the rest of the route reads it.

    Attributes:
        parent_id (str): The engine's parent id.
        part (str | None): The plan part's path, or None for a held order.
        price (decimal.Decimal | None): The new limit price, or None when it is not changed.
        trigger_price (decimal.Decimal | None): The new trigger price, or None when it is not changed.
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
            InvalidOrderError: When the body is not an object, `parent_id` is missing, `part` is not a path, a field that cannot change is given, a trigger price is given without a part, or nothing to change is given.
        """
        if not isinstance(body, dict):
            raise InvalidOrderError('the request body must be a JSON object')
        parent_id = body.get('parent_id')
        if not isinstance(parent_id, str) or not parent_id:
            raise InvalidOrderError('parent_id must name a parent')
        self.parent_id = parent_id
        part = body.get('part')
        if part is not None and (not isinstance(part, str) or not part):
            raise InvalidOrderError('part must name a part of the plan, such as root.first')
        self.part = part
        for field_name in OTHER_FIELD_NAMES:
            if body.get(field_name) is None:
                continue
            if part is not None:
                raise InvalidOrderError(
                    f'a plan part that has not been sent can only change its price, trigger_price and quantity, not {field_name}'
                )
            raise InvalidOrderError(
                f'an order named by parent_id is still held, so only its price and quantity can change, not {field_name}'
            )
        raw_dry_run = body.get('dry_run')
        if raw_dry_run is None:
            raw_dry_run = query_arguments.get('dry_run')
        self.dry_run = self.parse_flag('dry_run', raw_dry_run)
        self.quantity = self.parse_whole_number(body, 'quantity', 1)
        self.price = self.parse_price(body, 'price')
        self.trigger_price = self.parse_price(body, 'trigger_price')
        if self.trigger_price is not None and self.part is None:
            raise InvalidOrderError('an order named by parent_id alone is still held, so only its price and quantity can change, not trigger_price; name a plan part with part to change its trigger_price')
        if self.quantity is None and self.price is None and self.trigger_price is None:
            if self.part is None:
                raise InvalidOrderError('give price or quantity to change')
            raise InvalidOrderError('give price, trigger_price or quantity to change')

    def command_arguments(self):
        """The arguments of the engine's `modify_held` command.

        Returns:
            dict: `parent_id`, `price` as text or None, `quantity` and `dry_run`, and for a part also `part` and `trigger_price` as text or None.
        """
        price = None
        if self.price is not None:
            price = str(self.price)
        arguments = {
            'parent_id': self.parent_id,
            'price': price,
            'quantity': self.quantity,
            'dry_run': self.dry_run,
        }
        if self.part is not None:
            trigger_price = None
            if self.trigger_price is not None:
                trigger_price = str(self.trigger_price)
            arguments['part'] = self.part
            arguments['trigger_price'] = trigger_price
        return arguments
