"""Walks a buy at 1000, held after its price trigger, through a rise to 1005 and a fall back to 1000.

The order's own trigger waits for the last price to reach 1005. `HeldAfterCondition.is_met` asks that trigger first, and once it has fired, remembers so and asks only whether the best offer has reached the limit of 1000. The trigger fires at 1005, when the offer is far above the limit, so nothing is sent; when the price falls back to 1000, the trigger itself no longer holds, but the condition remembers that it fired and releases the order. A plain `all` of the two conditions would never release it, because they are never true on the same tick. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/held_after_condition/HeldAfterCondition/example_1_held_after_a_price_touch.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.condition_group import (
    ConditionGroup,
)
from unified_broker_interface.utilities.order_engine.utilities.held_after_condition import (
    HeldAfterCondition,
)
from unified_broker_interface.utilities.order_engine.utilities.limit_marketable_condition import (
    LimitMarketableCondition,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.price_crosses_condition import (
    PriceCrossesCondition,
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


class HeldAfterAPriceTouchExample:
    """Compares the held-after condition with a plain `all` over three quotes."""

    def quote(self, bid, offer):
        """A quote whose last price is the offer and whose touch is at the given prices.

        Args:
            bid (float): The best bid.
            offer (float): The best offer.

        Returns:
            dict: The quotes, by instrument id.
        """
        return {
            'NSE:INFY': {
                'last_price': offer,
                'depth': {
                    'buy': [
                        {
                            'price': bid,
                            'quantity': 100,
                        },
                    ],
                    'sell': [
                        {
                            'price': offer,
                            'quantity': 100,
                        },
                    ],
                },
            },
        }

    def trigger(self):
        """The order's own trigger: the last price at or above 1005.

        Returns:
            PriceCrossesCondition: The trigger.
        """
        return PriceCrossesCondition(decimal.Decimal('1005'), 'at_or_above', 'last', None, 'none', None)

    def run(self):
        """Prints, for each quote, whether each way of joining the two conditions releases the order.

        Returns:
            None: This method returns nothing.
        """
        context = StandInContext({
            'transaction_type': 'BUY',
            'order_type': 'LIMIT',
            'price': '1000',
            'quantity': 10,
        })
        held_after = HeldAfterCondition(self.trigger())
        plain_all = ConditionGroup('all', [self.trigger(), LimitMarketableCondition()])
        print('described:', held_after.described())
        print('needs prices:', held_after.needs_prices(), 'watches others:', held_after.instruments())
        held_memory = {}
        all_memory = {}
        held_after.prepare(context, held_memory)
        plain_all.prepare(context, all_memory)
        steps = [
            ('offer 1000.05, below the trigger', self.quote(1000.00, 1000.05)),
            ('offer 1005.00, the trigger fires', self.quote(1004.95, 1005.00)),
            ('offer 1000.00, back at the limit', self.quote(999.95, 1000.00)),
        ]
        for label, quotes in steps:
            held_releases = held_after.is_met(context, held_memory, quotes, 0, 'BUY', 'BUY')
            all_releases = plain_all.is_met(context, all_memory, quotes, 0, 'BUY', 'BUY')
            print(f'{label}: held after releases {held_releases}, plain all releases {all_releases}, fired {held_memory.get("fired") is True}')


if __name__ == '__main__':
    HeldAfterAPriceTouchExample().run()
