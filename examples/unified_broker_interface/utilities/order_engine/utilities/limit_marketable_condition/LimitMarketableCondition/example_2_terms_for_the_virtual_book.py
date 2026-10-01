"""Readies a limit_marketable trigger when a plan is placed, and shows the market order it refuses.

`LimitMarketableCondition.prepare` checks the order with `limit_price` and writes the terms it is held at into the trigger's memory, which `bin/unified/orders/virtual_book` reads to follow its place in the queue. A market order has no limit to be held at, so it is refused with `400`, as today's virtual limit type refuses it. `estimate` then reads what the book has stored under the parent id and the order's path. Redis is a small stand-in.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/limit_marketable_condition/LimitMarketableCondition/example_2_terms_for_the_virtual_book.py
"""

import decimal
import json
import logging

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.limit_marketable_condition import (
    LimitMarketableCondition,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.virtual_book import (
    ESTIMATES_KEY,
)


class StandInContext:
    """Stands in for the order's view of the plan order: its body, and quotes read through `MarketView`.

    Attributes:
        instrument_id (str): The order's instrument.
        body (dict): The order's settings.
    """

    def __init__(self, body):
        """Builds the context.

        Args:
            body (dict): The order's settings.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = 'NSE:INFY'
        self.body = body

    def view(self, quotes, instrument_id=None):
        """The order's instrument's market, with a tick of 0.05.

        Args:
            quotes (dict): The quotes, by instrument id.
            instrument_id (str | None): Unused, since only the order's own instrument is read.

        Returns:
            MarketView: The view.
        """
        del instrument_id
        return MarketView(quotes.get(self.instrument_id), decimal.Decimal('0.05'))


class StandInCache:
    """Stands in for Redis, holding the queue estimates.

    Attributes:
        hashes (dict): Each hash's fields, by key.
    """

    def __init__(self, hashes):
        """Builds the cache.

        Args:
            hashes (dict): Each hash's fields, by key.

        Returns:
            None: This method returns nothing.
        """
        self.hashes = hashes

    def hget(self, key, field):
        """Reads one hash field.

        Args:
            key (str): The hash.
            field (str): The field.

        Returns:
            str | None: The value, or None.
        """
        return self.hashes.get(key, {}).get(field)


class StandInPlacement:
    """Stands in for the placement, which holds the Redis client.

    Attributes:
        cache (StandInCache): The cache.
    """

    def __init__(self, cache):
        """Builds the placement.

        Args:
            cache (StandInCache): The cache.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache


class StandInParent:
    """Stands in for the plan's parent record.

    Attributes:
        parent_order_id (str): The parent's id.
    """

    def __init__(self, parent_order_id):
        """Builds the parent.

        Args:
            parent_order_id (str): The parent's id.

        Returns:
            None: This method returns nothing.
        """
        self.parent_order_id = parent_order_id


class StandInPlanOrder:
    """Stands in for the plan order: its parent, placement and logger.

    Attributes:
        parent (StandInParent): The parent.
        placement (StandInPlacement): The placement.
        logger (logging.Logger): The logger.
    """

    def __init__(self, cache):
        """Builds the plan order.

        Args:
            cache (StandInCache): The cache.

        Returns:
            None: This method returns nothing.
        """
        self.parent = StandInParent('plan-1')
        self.placement = StandInPlacement(cache)
        self.logger = logging.getLogger('example')


class TermsForTheVirtualBookExample:
    """Prepares a limit order and a market order, then reads an estimate."""

    def run(self):
        """Prints the memory written, the refusal and the estimate.

        Returns:
            None: This method returns nothing.
        """
        condition = LimitMarketableCondition()
        limit = StandInContext({
            'transaction_type': 'BUY',
            'order_type': 'LIMIT',
            'price': '1498.50',
            'quantity': 20,
        })
        memory = {}
        condition.prepare(limit, memory)
        print('limit price:', condition.limit_price(limit))
        print('memory written:', memory)
        market = StandInContext({
            'transaction_type': 'BUY',
            'order_type': 'MARKET',
            'price': None,
            'quantity': 20,
        })
        try:
            condition.prepare(market, {})
        except RefusedRequestError as error:
            print(f'market order refused with {error.status}: {error.body["error"]}')
        cache = StandInCache({
            ESTIMATES_KEY: {
                'plan-1/root': json.dumps({
                    'queue_filled': 6,
                    'filled': 6,
                }),
            },
        })
        plan_order = StandInPlanOrder(cache)
        print('estimate for root:', condition.estimate(plan_order, 'root'))
        print('estimate for root.then.0:', condition.estimate(plan_order, 'root.then.0'))


if __name__ == '__main__':
    TermsForTheVirtualBookExample().run()
