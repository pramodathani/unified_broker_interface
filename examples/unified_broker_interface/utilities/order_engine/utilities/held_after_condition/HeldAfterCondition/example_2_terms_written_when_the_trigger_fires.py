"""Shows that the held terms the virtual book reads are written when the order's own trigger fires, and that a market order cannot be held.

`HeldAfterCondition.prepare` readies the order's own trigger and checks the order is a LIMIT order with a price, refusing a market order with HTTP 400, but writes no held terms. The virtual book estimates queue position only for orders whose memory carries held terms, so it does not start counting until `is_met` sees the trigger fire and writes them, which is when a resting order would have joined the queue. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/held_after_condition/HeldAfterCondition/example_2_terms_written_when_the_trigger_fires.py
"""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.held_after_condition import (
    HeldAfterCondition,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.price_crosses_condition import (
    PriceCrossesCondition,
)


class StandInContext:
    """Stands in for the order's view of the plan order: its instrument, its body, and quotes read through `MarketView`.

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


class TermsWrittenWhenTheTriggerFiresExample:
    """Prints the condition's memory before and after its trigger fires, and a refused market order."""

    def quote(self, last_price):
        """A quote whose last price and best offer are the given price.

        Args:
            last_price (float): The last price.

        Returns:
            dict: The quotes, by instrument id.
        """
        return {
            'NSE:INFY': {
                'last_price': last_price,
                'depth': {
                    'buy': [
                        {
                            'price': last_price - 0.05,
                            'quantity': 100,
                        },
                    ],
                    'sell': [
                        {
                            'price': last_price,
                            'quantity': 100,
                        },
                    ],
                },
            },
        }

    def run(self):
        """Prepares and fires the condition for a limit order, then prepares it for a market order.

        Returns:
            None: This method returns nothing.
        """
        condition = HeldAfterCondition(
            PriceCrossesCondition(decimal.Decimal('995'), 'at_or_below', 'last', None, 'none', None),
        )
        limit_order = StandInContext({
            'transaction_type': 'BUY',
            'order_type': 'LIMIT',
            'price': '990',
            'quantity': 10,
        })
        memory = {}
        condition.prepare(limit_order, memory)
        print('after prepare:', memory)
        released = condition.is_met(limit_order, memory, self.quote(994.0), 0, 'BUY', 'BUY')
        print('after the trigger fires at 994:', memory, 'released', released)
        market_order = StandInContext({
            'transaction_type': 'BUY',
            'order_type': 'MARKET',
            'quantity': 10,
        })
        try:
            condition.prepare(market_order, {})
        except RefusedRequestError as refusal:
            print('a market order:', refusal.status, refusal.body.get('error'))


if __name__ == '__main__':
    TermsWrittenWhenTheTriggerFiresExample().run()
