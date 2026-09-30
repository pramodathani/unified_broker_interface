"""Shows which price a trigger watches, which way it fires, and how `double_last` and `held` make it wait for confirmation.

A caller chooses what a `PriceTrigger` compares with its level through `trigger_on`: the last traded price (the default), the best bid, the best offer, or the mid. Two more choices watch the last price but ask for confirmation first: `double_last` fires only on the second tick in a row that reaches the level, and `held` fires only once the level has stayed reached for `hold_seconds`. The direction defaults to "at or below" for a buy and "at or above" for a sell, and the caller may name the other one with `trigger_direction`.

This program builds a sell of 50 shares that waits for the price to rise to 1,520, and asks it each of these questions in turn, changing `trigger_on` between them. It never fires, so the only stand-in it needs is a parent store that counts saves, because the confirmation count is kept in the parent's parameters and saved on each tick. The small subclass `TouchSellOrder` exists only because `PriceTrigger` leaves `child_order` to its subclasses.

Notice that a tick that falls back below the level starts the `double_last` count again, and that `held` fires at 1,759,205,010, ten seconds after the level was first reached.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/price_trigger/PriceTrigger/example_2_choosing_and_confirming_the_watched_price.py
"""

import decimal
import logging

from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.price_trigger import (
    PriceTrigger,
)

INSTRUMENT_ID = '9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d'


class TouchSellOrder(PriceTrigger):
    """A sell that waits for the price to rise to a level and then takes the best bid."""

    SYNTHETIC_TYPE = 'touch_sell'

    def child_order(self, order, view):
        """A limit at the best bid.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.
            view (MarketView): The traded instrument's quote.

        Returns:
            PlaceOrderRequest | None: The order to send, or None when there is no bid.
        """
        bid = view.best_bid()
        if bid is None:
            return None
        return self.priced(order, bid)


class CountingParentStore:
    """Stands in for the Redis copy of the parent, only counting how often it is written.

    Attributes:
        saves (int): How many times the parent was saved.
    """

    def __init__(self):
        """Builds the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.saves = 0

    def save(self, parent):
        """Counts one save.

        Args:
            parent (ParentOrder): The parent.

        Returns:
            None: This method returns nothing.
        """
        self.saves = self.saves + 1


class ChoosingTheWatchedPriceExample:
    """Asks one sell trigger which price it watches and whether each tick confirms it.

    Attributes:
        parent_store (CountingParentStore): The stand-in parent store.
        trigger (TouchSellOrder): The order being shown.
        view (MarketView): A quote with the last trade at 1,519.50, the bid at 1,519.40 and the offer at 1,520.60.
    """

    def __init__(self):
        """Builds the trigger and a quote to read.

        Returns:
            None: This method returns nothing.
        """
        parent = ParentOrder('7c1d2e3f-0000-4000-8000-000000000002')
        parent.synthetic_type = TouchSellOrder.SYNTHETIC_TYPE
        parent.instrument_id = INSTRUMENT_ID
        parent.body = {
            'instrument_id': INSTRUMENT_ID,
            'transaction_type': 'SELL',
            'product': 'MIS',
            'order_type': 'MARKET',
            'quantity': 50,
        }
        parent.parameters = {
            'type': TouchSellOrder.SYNTHETIC_TYPE,
            'trigger_price': '1520',
            'tick_size': '0.05',
        }
        self.parent_store = CountingParentStore()
        self.trigger = TouchSellOrder(
            parent,
            None,
            None,
            self.parent_store,
            logging.getLogger('example'),
        )
        quote = {
            'last_price': 1519.50,
            'depth': {
                'buy': [
                    {
                        'price': 1519.40,
                        'quantity': 300,
                    },
                ],
                'sell': [
                    {
                        'price': 1520.60,
                        'quantity': 150,
                    },
                ],
            },
        }
        self.view = MarketView(quote, decimal.Decimal('0.05'))

    def choose(self, trigger_on, hold_seconds=None):
        """Sets the caller's `trigger_on`, and `hold_seconds` when given, starting any confirmation count again.

        Args:
            trigger_on (str | None): The choice, or None for the default.
            hold_seconds (int | None): The hold time for `held`.

        Returns:
            None: This method returns nothing.
        """
        parameters = {
            'type': TouchSellOrder.SYNTHETIC_TYPE,
            'trigger_price': '1520',
            'tick_size': '0.05',
        }
        if trigger_on is not None:
            parameters['trigger_on'] = trigger_on
        if hold_seconds is not None:
            parameters['hold_seconds'] = hold_seconds
        self.trigger.parent.parameters = parameters

    def run(self):
        """Prints each reading and each confirmation.

        Returns:
            None: This method returns nothing.
        """
        level = self.trigger.read_level()
        print(f'Level: {level}, watching instrument {self.trigger.watched_instrument()}')
        print(f'Default direction for a BUY: {self.trigger.default_direction("BUY")}, for a SELL: {self.trigger.default_direction("SELL")}')
        direction = self.trigger.direction('SELL')
        print(f'This sell fires {direction}')
        for trigger_on in [
            None,
            'bid',
            'ask',
            'mid',
        ]:
            self.choose(trigger_on)
            price = self.trigger.watched_price(self.view)
            reached = self.trigger.has_triggered(price, level, direction)
            print(f'trigger_on={self.trigger.read_trigger_on()}: watches {price}, reached={reached}')
        self.trigger.parent.parameters['trigger_direction'] = 'at_or_below'
        print(f'Named direction at_or_below: 1519.50 reaches 1520 {self.trigger.has_triggered(decimal.Decimal("1519.50"), level, self.trigger.direction("SELL"))}')

        self.choose('double_last')
        print('double_last, one tick at a time:')
        for moment, reached in [
            (1759205000.0, True),
            (1759205001.0, False),
            (1759205002.0, True),
            (1759205003.0, True),
        ]:
            confirmed = self.trigger.is_confirmed(reached, moment)
            print(f'  reached={reached}: confirmed={confirmed}, count kept={self.trigger.parent.parameters.get("reached_ticks")}')

        self.choose('held', 10)
        print(f'held needs {self.trigger.read_hold_seconds()} seconds:')
        for moment in [
            1759205000.0,
            1759205004.0,
            1759205010.0,
        ]:
            confirmed = self.trigger.is_confirmed(True, moment)
            print(f'  reached at {moment}: confirmed={confirmed}, reached since {self.trigger.parent.parameters.get("reached_since")}')
        print(f'Saves of the parent while counting: {self.parent_store.saves}')


if __name__ == '__main__':
    ChoosingTheWatchedPriceExample().run()
