"""Shows that a held stop protecting a long position is held as a sell, though its body names the buy that opened the position.

A stop that protects a long is written with the opening side, BUY, in its body, and is sent on the other side, SELL. When its trigger fires, `HeldAfterCondition.is_met` writes the held terms the virtual book and the paper venue read, and they must carry the side the order will be sent on, so the queue estimate and any paper fill use the bid side of the book. The bid here gaps from above the trigger to below the limit in one tick, so the stop fires but is not released. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/held_after_condition/HeldAfterCondition/example_3_held_stop_takes_the_sending_side.py
"""

import decimal

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
        self.instrument_id = 'NFO:NIFTY_PE'
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


class HeldStopTakesTheSendingSideExample:
    """Fires a held stop that protects a long and prints the side its held terms carry."""

    def quote(self, best_bid, best_offer):
        """A quote with the given best bid and best offer.

        Args:
            best_bid (float): The best bid.
            best_offer (float): The best offer.

        Returns:
            dict: The quotes, by instrument id.
        """
        return {
            'NFO:NIFTY_PE': {
                'last_price': best_bid,
                'depth': {
                    'buy': [
                        {
                            'price': best_bid,
                            'quantity': 65,
                        },
                    ],
                    'sell': [
                        {
                            'price': best_offer,
                            'quantity': 65,
                        },
                    ],
                },
            },
        }

    def run(self):
        """Prepares the stop, gaps the bid through its trigger and limit, and prints the held terms.

        Returns:
            None: This method returns nothing.
        """
        condition = HeldAfterCondition(
            PriceCrossesCondition(decimal.Decimal('272.05'), 'at_or_below', 'bid', None, 'none', None),
        )
        protecting_stop = StandInContext({
            'transaction_type': 'BUY',
            'order_type': 'LIMIT',
            'price': '271.05',
            'quantity': 65,
        })
        memory = {}
        condition.prepare(protecting_stop, memory)
        released = condition.is_met(protecting_stop, memory, self.quote(272.55, 273.25), 0, 'BUY', 'SELL')
        print('bid 272.55, above the trigger: fired', memory.get('fired') is True, 'released', released)
        released = condition.is_met(protecting_stop, memory, self.quote(270.60, 271.35), 1, 'BUY', 'SELL')
        print('bid 270.60, below the limit: fired', memory.get('fired') is True, 'released', released)
        print('held side:', memory['held']['transaction_type'])
        released = condition.is_met(protecting_stop, memory, self.quote(271.10, 271.80), 2, 'BUY', 'SELL')
        print('bid 271.10, back above the limit: released', released)


if __name__ == '__main__':
    HeldStopTakesTheSendingSideExample().run()
