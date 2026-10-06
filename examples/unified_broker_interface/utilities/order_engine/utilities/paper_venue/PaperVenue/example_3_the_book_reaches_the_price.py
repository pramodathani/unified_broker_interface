"""Fills a paper buy of 250 at 999.50 when the offers fall to its price, taking only what the book holds there.

When the other side of the book reaches a paper order's price, a real order sent then would take only the offers at or below its limit, at their own prices. So `PaperVenue.fill` walks those levels once, with `walk_the_touch`, and fills what they hold; the rest keeps resting and fills later from the queue, at the limit. Here the offers are 100 at 999.45 and 100 at 999.50, then 999.55 and above, so the touch fills 200 at 999.475, and the last 50 fill at 999.50 once a trade below the price shows the queue has gone. Redis, the plan order and the quote are small stand-ins that print what they are asked to record.

Notice that the second tick, which still shows the book at the price, takes nothing more: the book is walked only once, and the final average is 999.48.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/paper_venue/PaperVenue/example_3_the_book_reaches_the_price.py
"""

import copy
import decimal
import json
import logging

from unified_broker_interface.utilities.order_engine.utilities.limit_marketable_condition import (
    LimitMarketableCondition,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.paper_venue import (
    PaperVenue,
)
from unified_broker_interface.utilities.order_engine.utilities.virtual_book import (
    ESTIMATES_KEY,
)

INSTRUMENT = 'NSE:NIFTY25OCT23800CE'


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

    def store_estimate(self, key, queue_filled, filled):
        """Writes an estimate as the virtual book would.

        Args:
            key (str): The order's key.
            queue_filled (int): How much the queue alone would have filled.
            filled (int): That, or the whole order once the other side has reached the price.

        Returns:
            None: This method returns nothing.
        """
        self.hashes[ESTIMATES_KEY][key] = json.dumps({
            'queue_filled': queue_filled,
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
        instrument_id (str): The instrument.
        state (str): The parent's state.
    """

    def __init__(self):
        """Builds a parent that has just been received.

        Returns:
            None: This method returns nothing.
        """
        self.parent_order_id = 'plan-1'
        self.instrument_id = INSTRUMENT
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

    def view(self, quotes):
        """The market, as this parent's quote and a 0.05 tick show it.

        Args:
            quotes (dict): The quotes the tick carried.

        Returns:
            MarketView: The reader.
        """
        return MarketView(quotes.get(self.parent.instrument_id), decimal.Decimal('0.05'))

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
        print(f'  event {event["event"]}: {event["filled_quantity"]} of {event["quantity"]}, average {event["average_price"]}, touch {event["detail"]["touch"]}')

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


class BookReachesThePriceExample:
    """Feeds three ticks to one paper order whose price the offers reach."""

    def quotes(self):
        """The tick's quotes: bids from 999.40 and offers from 999.45, 100 at each of five levels.

        Returns:
            dict: The quotes, by instrument.
        """
        bids = []
        offers = []
        for index in range(5):
            bids.append({
                'price': round(999.40 - index * 0.05, 2),
                'quantity': 100,
                'orders': 1,
            })
            offers.append({
                'price': round(999.45 + index * 0.05, 2),
                'quantity': 100,
                'orders': 1,
            })
        return {
            INSTRUMENT: {
                'stale': False,
                'depth': {
                    'buy': bids,
                    'sell': offers,
                },
            },
        }

    def run(self):
        """Prints what each tick records, then the venue's helpers on their own.

        Returns:
            None: This method returns nothing.
        """
        held = {
            'instrument_id': INSTRUMENT,
            'transaction_type': 'BUY',
            'price': '999.50',
            'quantity': 250,
        }
        cache = StandInCache()
        plan_order = StandInPlanOrder(cache, held)
        part = StandInPart()
        venue = PaperVenue()
        ticks = [
            ('the offers reach 999.50', 0, 250),
            ('the book is still at the price', 0, 250),
            ('a trade below 999.50 empties the queue', 250, 250),
        ]
        for name, queue_filled, filled in ticks:
            cache.store_estimate('plan-1/root', queue_filled, filled)
            print(f'{name}:')
            print(f'  recorded a fill: {venue.fill(plan_order, part, self.quotes())}')
        print('final record:', plan_order.records['root']['state'], plan_order.records['root'].get('paper_filled'))
        limit = venue.price('999.50')
        print(f'Walking 120 against the offers: {venue.walk_the_touch(plan_order, self.quotes(), "BUY", limit, 120)}')
        print(f'Average of 200 at 999.475 and 50 at the limit: {venue.average_price(250, 200, 999.475, limit)}')
        print(f'Counts read from an estimate: {venue.whole_number(7)}, {venue.whole_number(True)}, {venue.whole_number("7")}')
        print(f'Prices read from memory: {venue.price("999.50")}, {venue.price(0)}, {venue.price(None)}')


if __name__ == '__main__':
    BookReachesThePriceExample().run()
