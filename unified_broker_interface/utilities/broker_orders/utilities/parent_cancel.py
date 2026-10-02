"""A cancel of one of the order engine's parents, as `DELETE /api/orders/cancel` takes it with `parent_id`."""

from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    OrderRequest,
)

OTHER_FIELD_NAMES = [
    'order_id',
    'broker',
]


class ParentCancel(OrderRequest):
    """One cancel of an order the engine manages, named by its parent rather than by a broker order: the whole parent, or one part of a plan.

    The parent is named by the `parent_id` the place route answered with, and a part of a plan also by its `part` path, as `GET /api/orders/parents` shows it. A parent may have placed nothing yet, such as an armed trigger, and a part may not have been sent, so neither has a broker order id to name it by. `dry_run` checks the cancel without making it, and is read from the body first and the query string second, as the rest of the route reads it.

    Attributes:
        parent_id (str): The engine's parent id.
        part (str | None): The plan part's path, or None for the whole parent.
        dry_run (bool): Whether to check the cancel without making it.
    """

    def __init__(self, body, query_arguments):
        """Validates the cancel.

        Args:
            body (object): The decoded JSON body, or one entry of the `orders` list.
            query_arguments (werkzeug.datastructures.MultiDict): The query string arguments.

        Returns:
            None: This method returns nothing.

        Raises:
            InvalidOrderError: When the body is not an object, `parent_id` is missing, `part` is not a path, `order_id` or `broker` is given beside `parent_id`, or `dry_run` is invalid.
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
            if body.get(field_name) is not None:
                raise InvalidOrderError(
                    f'name the order either by parent_id or by order_id, not both; {field_name} cannot be given with parent_id'
                )
        raw_dry_run = body.get('dry_run')
        if raw_dry_run is None:
            raw_dry_run = query_arguments.get('dry_run')
        self.dry_run = self.parse_flag('dry_run', raw_dry_run)

    def command_arguments(self):
        """The arguments of the engine's `cancel_parent` command.

        Returns:
            dict: `parent_id`, with `part` when a part is named and `dry_run` when it is true.
        """
        arguments = {
            'parent_id': self.parent_id,
        }
        if self.part is not None:
            arguments['part'] = self.part
        if self.dry_run:
            arguments['dry_run'] = True
        return arguments
