"""A list of modifications or cancels in one request body, validated, and the result entries it is answered with.

`PUT /api/orders/modify` and `DELETE /api/orders/cancel` take a body with an `orders` list as their list form. Each item names one order exactly as the single form's body does, with `order_id`, an optional `broker` and, for a modify, the fields to change. `dry_run` is the only other key the list takes, beside `orders` or in the query string, and it applies to every order, so no order can go live while its neighbours are only shown.

An item that is not a valid order, or that repeats an order an earlier item already names, gets its own 400 entry, and the other items are still answered. A body whose `orders` is not a non-empty list, or that has any other key beside it, is refused as a whole.
"""

from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    OrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)


class OrderChangeList(OrderRequest):
    """One list of modifications or cancels as the caller sent it, each item validated.

    Attributes:
        dry_run (bool): Whether every order is only shown rather than sent.
        entries (list): One entry per item of `orders`, in order: the validated request, a `CancelOrderRequest` or a `ModifyOrderRequest`, or the `RefusedRequestError` saying why the item is not one.
    """

    def __init__(self, body, query_arguments, request_class, broker_names):
        """Validates the list and every item in it.

        Args:
            body (dict): The decoded JSON body, which holds `orders`.
            query_arguments (werkzeug.datastructures.MultiDict): The query string arguments.
            request_class (type): `CancelOrderRequest` or `ModifyOrderRequest`, which validates one item.
            broker_names (list): Every broker's name, for checking `broker`.

        Returns:
            None: This method returns nothing.

        Raises:
            InvalidOrderError: When `orders` is not a non-empty list, the body or query string has a key other than `orders` and `dry_run`, or `dry_run` is invalid.
        """
        items = body.get('orders')
        if not isinstance(items, list) or not items:
            raise InvalidOrderError('orders must be a non-empty list')
        for name in body:
            if name not in ('orders', 'dry_run'):
                raise InvalidOrderError(f'a list takes only orders and dry_run, so give {name} inside each order')
        for name in query_arguments:
            if name != 'dry_run':
                raise InvalidOrderError(f'a list takes only dry_run in the query string, so give {name} inside each order')

        raw_dry_run = body.get('dry_run')
        if raw_dry_run is None:
            raw_dry_run = query_arguments.get('dry_run')
        self.dry_run = self.parse_flag('dry_run', raw_dry_run)

        self.entries = []
        for item in items:
            self.entries.append(self.parse_item(item, request_class, broker_names))
        self.refuse_repeated_orders()

    def parse_item(self, item, request_class, broker_names):
        """Validates one item of the list.

        Args:
            item (object): The item as decoded from JSON.
            request_class (type): `CancelOrderRequest` or `ModifyOrderRequest`.
            broker_names (list): Every broker's name, for checking `broker`.

        Returns:
            CancelOrderRequest | ModifyOrderRequest | RefusedRequestError: The validated request, or the refusal saying why the item is not one.
        """
        if not isinstance(item, dict):
            return RefusedRequestError.refusal('each entry of orders must be an object', 400)
        if 'dry_run' in item:
            return RefusedRequestError.refusal(
                'dry_run applies to the whole list, so give it beside orders rather than inside an order',
                400,
            )
        try:
            return request_class(item, {}, broker_names)
        except InvalidOrderError as error:
            return RefusedRequestError.refusal(str(error), 400)

    def refuse_repeated_orders(self):
        """Replaces every item that names an order an earlier item already names with a refusal.

        Two items name the same order when their order ids are equal and their brokers are equal, or either gives no broker. Sending two changes to one order in one request is almost always a mistake, and each costs a message from the broker's daily order allowance.

        Returns:
            None: This method returns nothing.
        """
        earlier_by_order_id = {}
        for request_index, entry in enumerate(self.entries):
            if isinstance(entry, RefusedRequestError):
                continue
            earlier = earlier_by_order_id.setdefault(entry.order_id, [])
            repeated_index = None
            for earlier_index, earlier_broker in earlier:
                if earlier_broker is None or entry.broker is None or earlier_broker == entry.broker:
                    repeated_index = earlier_index
                    break
            if repeated_index is None:
                earlier.append((request_index, entry.broker))
                continue
            self.entries[request_index] = RefusedRequestError.refusal(
                f'this order is already named at request_index {repeated_index}',
                400,
                order_id=entry.order_id,
            )

    def order_ids(self):
        """The distinct order ids of the valid items, in the order they first appear.

        Returns:
            list: The order ids to look up in the brokers' order books.
        """
        order_ids = []
        seen = set()
        for entry in self.entries:
            if isinstance(entry, RefusedRequestError):
                continue
            if entry.order_id not in seen:
                seen.add(entry.order_id)
                order_ids.append(entry.order_id)
        return order_ids

    def results(self, answers):
        """The result entries for the whole list.

        Args:
            answers (list): One `(body, status)` pair per entry, in the same order.

        Returns:
            list: One dictionary per item, with `request_index`, `status` and `response`, the body the single form would have answered with.
        """
        results = []
        for request_index, answer in enumerate(answers):
            answer_body, status = answer
            results.append({
                'request_index': request_index,
                'status': status,
                'response': answer_body,
            })
        return results
