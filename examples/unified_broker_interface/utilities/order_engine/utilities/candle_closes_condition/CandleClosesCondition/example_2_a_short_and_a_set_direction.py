"""Shows the condition for a short, which waits for a close at or above the level, and one given its direction outright.

With no direction, `CandleClosesCondition.effective_direction` follows the side that opened the position, so a short, opened with a SELL, waits for a close at or above the level. A direction given outright is used whatever the side. With no last price nothing is added to the bars. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/candle_closes_condition/CandleClosesCondition/example_2_a_short_and_a_set_direction.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.candle_closes_condition import (
    CandleClosesCondition,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'


class StandInContext:
    '''Stands in for the order's view of the plan order, which reads a quote into a market view.'''

    def view(self, quotes):
        '''The market, with a tick of five paise.

        Args:
            quotes (dict): The quotes, by instrument id.

        Returns:
            MarketView: The view.
        '''
        return MarketView(quotes.get(INSTRUMENT_ID), decimal.Decimal('0.05'))


class QuoteMaker:
    '''Builds quotes with a last price.'''

    def last(self, price):
        '''The quotes a tick carries.

        Args:
            price (float): The last traded price.

        Returns:
            dict: The quotes, by instrument id.
        '''
        return {
            INSTRUMENT_ID: {
                'last_price': price,
            },
        }


class AShortAndASetDirectionExample:
    """Prints a short's condition and a set direction."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        condition = CandleClosesCondition(decimal.Decimal('1005'), None, 1.0)
        context = StandInContext()
        maker = QuoteMaker()
        memory = {}
        print(f'For a short: {condition.effective_direction("SELL")}; with no last price it holds {condition.is_met(context, memory, {}, 0.0, "SELL", "BUY")}')
        for now, price in ((0, 1000.00), (30, 1006.00), (60, 1006.00)):
            print(f'At {now} seconds, last {price}: holds {condition.is_met(context, memory, maker.last(price), float(now), "SELL", "BUY")}')
        fixed = CandleClosesCondition(decimal.Decimal('995'), 'at_or_above', 5.0)
        print(f'Given at_or_above outright, a long uses {fixed.effective_direction("BUY")}: {fixed.described()}')


if __name__ == '__main__':
    AShortAndASetDirectionExample().run()
