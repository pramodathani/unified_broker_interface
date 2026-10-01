"""Walks a long's candle close condition at 995, on one-minute bars, through a wick below the level and then a bar that closes below it.

`CandleClosesCondition.is_met` adds each tick's last price to the bars kept in its memory and answers only when a bar closes: the first bar dips to 990 but closes at 1,000, so nothing happens, and the second closes at 990, below the level. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/candle_closes_condition/CandleClosesCondition/example_1_a_wick_and_a_close.py
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


class AWickAndACloseExample:
    """Walks a long's candle close condition."""

    def run(self):
        """Prints each tick.

        Returns:
            None: This method returns nothing.
        """
        condition = CandleClosesCondition(decimal.Decimal('995'), None, 1.0)
        context = StandInContext()
        maker = QuoteMaker()
        memory = {}
        condition.prepare(context, memory)
        print(f'Reads quotes: {condition.needs_prices()}, watches: {condition.instruments()}, direction for a long: {condition.effective_direction("BUY")}')
        for now, price in ((0, 1000.00), (10, 990.00), (50, 1000.00), (70, 990.00), (110, 990.00), (130, 990.00)):
            print(f'At {now} seconds, last {price}: holds {condition.is_met(context, memory, maker.last(price), float(now), "BUY", "SELL")}')
        print(f'As a dry run shows it: {condition.described()}')


if __name__ == '__main__':
    AWickAndACloseExample().run()
