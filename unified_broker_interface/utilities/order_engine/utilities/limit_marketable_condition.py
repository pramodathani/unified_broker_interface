"""The trigger condition that holds when the other side of the book reaches the order's own limit price."""

import decimal
import json

import redis

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.virtual_book import (
    ESTIMATES_KEY,
    VirtualBook,
)


class LimitMarketableCondition:
    """A plan order's trigger that holds a limit order in the engine until it would fill straight away.

    It keeps the rules of today's virtual limit type. The order is a LIMIT order with a price, and the condition holds once the best price on the other side of the book reaches it: for a buy, when the best offer is at or below the limit, and for a sell, when the best bid is at or above it. An order sent then takes the other side and fills at once, at its limit or better. A quote marked stale is never acted on. When the plan is placed the condition writes the order's held terms into its memory, which `bin/unified/orders/virtual_book` reads to estimate how a resting order at the same price would have filled.
    """

    def needs_prices(self):
        """Whether this condition reads quotes, which it does.

        Returns:
            bool: True.
        """
        return True

    def instruments(self):
        """The instruments other than the order's own that this condition watches, which are none.

        Returns:
            list: An empty list.
        """
        return []

    def limit_price(self, plan_order):
        """The order's own limit price, which the other side has to reach.

        Args:
            plan_order (OrderContext): The order's view of the plan order.

        Returns:
            decimal.Decimal: The limit price.

        Raises:
            RefusedRequestError: With HTTP 400 when the order is not a LIMIT order with a price.
        """
        order_type = str(plan_order.body.get('order_type') or '').upper()
        price = plan_order.body.get('price')
        if order_type != 'LIMIT' or price is None:
            raise RefusedRequestError.refusal(
                'a virtual limit order is held at its own limit price, so it must be a LIMIT order with a price',
                400,
            )
        try:
            return decimal.Decimal(str(price))
        except decimal.InvalidOperation as error:
            raise RefusedRequestError.refusal(f'price must be a number, not {price!r}', 400) from error

    def prepare(self, plan_order, memory):
        """Checks the order is a limit order and writes the terms it is held at, for the virtual book to follow.

        Args:
            plan_order (OrderContext): The order's view of the plan order.
            memory (dict): The condition's memory, changed in place.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 400 when the order is not a LIMIT order with a price.
        """
        price = self.limit_price(plan_order)
        memory['held'] = {
            'instrument_id': plan_order.instrument_id,
            'transaction_type': str(plan_order.body.get('transaction_type') or '').upper(),
            'price': str(price),
            'quantity': plan_order.body.get('quantity'),
        }

    def is_met(self, plan_order, memory, quotes, now, opening_side, sending_side):
        """Whether the other side of the book has reached the limit price on a quote that is not stale.

        Args:
            plan_order (OrderContext): The order's view of the plan order.
            memory (dict): Unused.
            quotes (dict): The quotes the tick carried, by instrument id.
            now (float): Unused.
            opening_side (str): Unused.
            sending_side (str): BUY or SELL, the side the order will be sent on.

        Returns:
            bool: True when it holds.
        """
        del memory, now, opening_side
        view = plan_order.view(quotes)
        if view.is_stale():
            return False
        price = view.opposite_touch(sending_side)
        if price is None:
            return False
        limit = self.limit_price(plan_order)
        if sending_side == 'BUY':
            return price <= limit
        return price >= limit

    def estimate(self, plan_order, path):
        """What the virtual book last worked out about this order's place in the queue, or None.

        Args:
            plan_order (PlanOrder): The plan order, whose placement reads Redis.
            path (str): The order's path in the plan.

        Returns:
            dict | None: The stored estimate.
        """
        key = VirtualBook.part_key(plan_order.parent.parent_order_id, path)
        try:
            stored = plan_order.placement.cache.hget(ESTIMATES_KEY, key)
        except redis.RedisError as error:
            plan_order.logger.warning(f'The queue estimate for {key} could not be read: {error}')
            return None
        if not stored:
            return None
        try:
            document = json.loads(stored)
        except ValueError:
            return None
        if not isinstance(document, dict):
            return None
        return document

    def described(self):
        """This condition as a dry run shows it.

        Returns:
            dict: The condition's name.
        """
        return {
            'limit_marketable': {},
        }
