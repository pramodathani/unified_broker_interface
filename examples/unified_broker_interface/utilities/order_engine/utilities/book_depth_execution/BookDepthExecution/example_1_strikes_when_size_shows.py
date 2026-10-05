"""Walks a liquidity-seeking buy of twenty, limit 1000.10, through a book whose offers come inside its limit.

`BookDepthExecution.reachable_quantity` adds up the displayed offers no worse than the limit, and `due_pieces` strikes for the smaller of that and what is left once it reaches the minimum of ten. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/book_depth_execution/BookDepthExecution/example_1_strikes_when_size_shows.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.book_depth_execution import (
    BookDepthExecution,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)


INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'


class StandInPlanOrder:
    """Stands in for the plan order, which reads a quote into a market view."""

    def view(self, quotes):
        """The market, as the instrument's quote shows it, with a tick of five paise.

        Args:
            quotes (dict): The quotes, by instrument id.

        Returns:
            MarketView: The view.
        """
        return MarketView(quotes.get(INSTRUMENT_ID), decimal.Decimal('0.05'))

    def lot_size(self):
        """The lot every slice must be a whole number of, which for a share is one.

        Returns:
            int: One.
        """
        return 1


class StrikesWhenSizeShowsExample:
    """Asks a liquidity-seeking order what to send as the book changes."""

    def quotes_with_offers(self, offers):
        """The quotes a tick carries, with the given offers.

        Args:
            offers (list): Pairs of price and quantity, best first.

        Returns:
            dict: The quotes, by instrument id.
        """
        levels = []
        for price, quantity in offers:
            levels.append(
                {
                    'price': price,
                    'quantity': quantity,
                }
            )
        return {
            INSTRUMENT_ID: {
                'depth': {
                    'buy': [],
                    'sell': levels,
                },
            },
        }

    def run(self):
        """Prints each book.

        Returns:
            None: This method returns nothing.
        """
        execution = BookDepthExecution(decimal.Decimal('1000.10'), 10)
        plan_order = StandInPlanOrder()
        execution.begin(plan_order, {}, {}, 0.0)
        print(f'Reads quotes: {execution.needs_prices()}, paced by ticks: {execution.paced_by_ticks()}, grows by changing its order: {execution.changes_its_order_to_grow()}')
        books = [
            [
                (1000.15, 50),
            ],
            [
                (1000.10, 4),
                (1000.15, 50),
            ],
            [
                (1000.05, 6),
                (1000.10, 8),
                (1000.15, 50),
            ],
        ]
        for offers in books:
            quotes = self.quotes_with_offers(offers)
            reachable = execution.reachable_quantity(plan_order.view(quotes), 'BUY')
            due = execution.due_pieces(plan_order, {}, 20, [], quotes, 0.0, sending_side='BUY')
            print(f'Offers {offers}: reachable {reachable}, due {due}')
        print(f'As a dry run shows it: {execution.described()}')


if __name__ == '__main__':
    StrikesWhenSizeShowsExample().run()
