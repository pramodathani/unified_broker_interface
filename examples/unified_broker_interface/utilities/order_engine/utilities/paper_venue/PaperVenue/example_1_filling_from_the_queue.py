"""Fills a paper order of 10 from three queue estimates, as a resting buy at 1498.50 would have filled.

`PaperVenue.fill` reads what the virtual book estimates under the parent id and the order's path. A first fill moves the parent from received to working, each new fill is recorded as a `paper_filled` event at the limit price, and once the whole quantity has filled the order is done. Redis and the plan order are small stand-ins that print what they are asked to record.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/paper_venue/PaperVenue/example_1_filling_from_the_queue.py
"""

import copy
import json
import logging

from unified_broker_interface.utilities.order_engine.utilities.limit_marketable_condition import (
    LimitMarketableCondition,
)
from unified_broker_interface.utilities.order_engine.utilities.paper_venue import (
    PaperVenue,
)
from unified_broker_interface.utilities.order_engine.utilities.virtual_book import (
    ESTIMATES_KEY,
)


class StandInCache:
    """Stands in for Redis, holding the virtual book's queue estimates.

    Attributes:
        hashes (dict): Each hash's fields, by key.
    """

    def __init__(self):
        """Builds an empty cache.

        Returns:
            None: This method returns nothing.
        """
        self.hashes = {
            ESTIMATES_KEY: {},
        }

    def hget(self, key, field):
        """Reads one hash field.

        Args:
            key (str): The hash.
            field (str): The field.

        Returns:
            str | None: The value, or None.
        """
        return self.hashes.get(key, {}).get(field)

    def store_estimate(self, key, filled):
        """Writes an estimate as the virtual book would.

        Args:
            key (str): The order's key.
            filled (int): How much a resting order would have filled.

        Returns:
            None: This method returns nothing.
        """
        self.hashes[ESTIMATES_KEY][key] = json.dumps({
            'queue_filled': filled,
            'filled': filled,
        })


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
        state (str): The parent's state.
    """

    def __init__(self):
        """Builds a parent that has just been received.

        Returns:
            None: This method returns nothing.
        """
        self.parent_order_id = 'plan-1'
        self.state = 'received'


class StandInPlanOrder:
    """Stands in for the plan order, printing every event and state change it is asked to record.

    Attributes:
        parent (StandInParent): The parent.
        placement (StandInPlacement): The placement.
        logger (logging.Logger): The logger.
        records (dict): Each part's record, by path.
    """

    def __init__(self, cache, held):
        """Builds the plan order with one waiting paper order.

        Args:
            cache (StandInCache): The cache.
            held (dict): The terms the order's trigger wrote when the plan was placed.

        Returns:
            None: This method returns nothing.
        """
        self.parent = StandInParent()
        self.placement = StandInPlacement(cache)
        self.logger = logging.getLogger('example')
        self.records = {
            'root': {
                'state': 'waiting',
                'memory': {
                    'trigger': {
                        'held': held,
                    },
                },
            },
        }

    def part_record(self, path):
        """A copy of one part's record.

        Args:
            path (str): The part's path.

        Returns:
            dict: The record.
        """
        return copy.deepcopy(self.records.get(path) or {})

    def set_part_record(self, path, record, message):
        """Keeps one part's record and prints why it changed.

        Args:
            path (str): The part's path.
            record (dict): The record.
            message (str | None): Why it changed.

        Returns:
            None: This method returns nothing.
        """
        self.records[path] = record
        print(f'  part record: {message}')

    def record(self, event):
        """Prints an event.

        Args:
            event (dict): The event.

        Returns:
            None: This method returns nothing.
        """
        print(f'  event {event["event"]}: {event["filled_quantity"]} of {event["quantity"]} at {event["price"]}')

    def record_state(self, state, message):
        """Changes the parent's state and prints it.

        Args:
            state (str): The new state.
            message (str): Why.

        Returns:
            None: This method returns nothing.
        """
        self.parent.state = state
        print(f'  parent is now {state}: {message}')

    def json_number(self, value):
        """A price as a float.

        Args:
            value (object): The price.

        Returns:
            float | None: The price, or None.
        """
        if value is None:
            return None
        return float(value)


class StandInPart:
    """Stands in for the plan's one order: its path and its limit_marketable trigger.

    Attributes:
        path (str): The order's path.
        trigger (LimitMarketableCondition): The trigger.
    """

    def __init__(self):
        """Builds the order at the root of the plan.

        Returns:
            None: This method returns nothing.
        """
        self.path = 'root'
        self.trigger = LimitMarketableCondition()


class FillingFromTheQueueExample:
    """Feeds three estimates to one paper order."""

    def run(self):
        """Prints what each estimate records.

        Returns:
            None: This method returns nothing.
        """
        held = {
            'instrument_id': 'NSE:INFY',
            'transaction_type': 'BUY',
            'price': '1498.50',
            'quantity': 10,
        }
        cache = StandInCache()
        plan_order = StandInPlanOrder(cache, held)
        part = StandInPart()
        venue = PaperVenue()
        for filled in (0, 4, 10):
            cache.store_estimate('plan-1/root', filled)
            print(f'estimate says {filled} filled:')
            print(f'  recorded a fill: {venue.fill(plan_order, part)}')
        print('final record:', plan_order.records['root']['state'], plan_order.records['root'].get('reason'), plan_order.records['root'].get('paper_filled'))


if __name__ == '__main__':
    FillingFromTheQueueExample().run()
