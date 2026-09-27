"""A list of orders to place in one request body, validated, and the result entries it is answered with.

`POST /api/orders/place` takes a body with an `orders` list as its list form. Each item is one order exactly as the single form's body gives it, including a `synthetic` object for any order type the engine runs. `dry_run` is the only other key the list takes, and it applies to every order, so no order can go live while its neighbours are only shown.

An item that is not a valid order gets its own 400 entry, and the other items are still placed. A body whose `orders` is not a non-empty list no longer than the configured maximum, or that has any other key beside it, is refused as a whole.
"""

from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    OrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.place_order_request import (
    PlaceOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)


class PlaceOrderList(OrderRequest):
    """One list of orders to place as the caller sent it, each item validated.

    Attributes:
        dry_run (bool): Whether every order is only shown rather than sent.
        entries (list): One entry per item of `orders`, in order: the validated `PlaceOrderRequest`, or the `RefusedRequestError` saying why the item is not one.
        bodies (list): One entry per item: the body handed to the order engine, with `dry_run` set from the list and any `broker` removed, or None for an item that was refused.
    """

    def __init__(self, body, maximum_orders):
        """Validates the list and every item in it.

        Args:
            body (dict): The decoded JSON body, which holds `orders`.
            maximum_orders (int): The most orders one list may hold.

        Returns:
            None: This method returns nothing.

        Raises:
            InvalidOrderError: When `orders` is not a non-empty list, holds more than `maximum_orders` items, the body has a key other than `orders` and `dry_run`, or `dry_run` is invalid.
        """
        items = body.get('orders')
        if not isinstance(items, list) or not items:
            raise InvalidOrderError('orders must be a non-empty list')
        if len(items) > maximum_orders:
            raise InvalidOrderError(
                f'a list may hold at most {maximum_orders} orders, not {len(items)}'
            )
        for name in body:
            if name not in ('orders', 'dry_run'):
                raise InvalidOrderError(
                    f'a list takes only orders and dry_run, so give {name} inside each order'
                )
        self.dry_run = self.parse_flag('dry_run', body.get('dry_run'))
        self.entries = []
        self.bodies = []
        for item in items:
            self.add_item(item)

    def add_item(self, item):
        """Validates one item of the list and keeps it, or the reason it is refused.

        Args:
            item (object): The item as decoded from JSON.

        Returns:
            None: This method returns nothing.
        """
        if not isinstance(item, dict):
            self.refuse_item('each entry of orders must be an object')
            return
        if 'dry_run' in item:
            self.refuse_item(
                'dry_run applies to the whole list, so give it beside orders rather than inside an order'
            )
            return
        engine_body = dict(item)
        engine_body.pop('broker', None)
        if self.dry_run:
            engine_body['dry_run'] = True
        try:
            order = PlaceOrderRequest(engine_body)
        except InvalidOrderError as error:
            self.refuse_item(str(error))
            return
        self.entries.append(order)
        self.bodies.append(engine_body)

    def refuse_item(self, message):
        """Keeps a 400 refusal in place of one item.

        Args:
            message (str): Why the item is not a valid order.

        Returns:
            None: This method returns nothing.
        """
        self.entries.append(RefusedRequestError.refusal(message, 400))
        self.bodies.append(None)

    def results(self, answers):
        """The result entries for the whole list.

        Args:
            answers (list): One `(body, status)` pair per item, in the same order.

        Returns:
            list: One dictionary per item, with `request_index`, `intent_id` (None for an item refused before it reached the engine), `status` and `response`, the body the single form would have answered with.
        """
        results = []
        for request_index, answer in enumerate(answers):
            answer_body, status = answer
            intent_id = None
            if isinstance(answer_body, dict):
                intent_id = answer_body.get('intent_id')
            results.append({
                'request_index': request_index,
                'intent_id': intent_id,
                'status': status,
                'response': answer_body,
            })
        return results
