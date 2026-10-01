"""Shows that each member of a group keeps its own confirmation count, and that a group names every instrument its members watch.

A `ConditionGroup` hands each member its own memory under the member's position, so two `double_last` conditions in one group count their ticks separately, and every member is asked on every tick even when an earlier one has already said no. `instruments` gathers the instruments every member watches, each once, which is how the price ticker learns to fetch their quotes.

A small stand-in plays the plan order. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/condition_group/ConditionGroup/example_2_each_member_keeps_its_own_count.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.condition_group import (
    ConditionGroup,
)
from unified_broker_interface.utilities.order_engine.utilities.price_crosses_condition import (
    PriceCrossesCondition,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'
FUTURE_ID = '11111111-1111-5111-8111-000000000004'


class QuoteBuilder:
    """Builds live quotes in the shape `unified:quotes:live` holds them, with five levels behind each side."""

    def book_at(self, bid, offer, last_price=None):
        """A quote whose best bid and offer sit where the program wants them.

        Args:
            bid (float): The best bid.
            offer (float): The best offer.
            last_price (float | None): The last traded price, or None for the offer.

        Returns:
            dict: The quote.
        """
        buy_levels = []
        sell_levels = []
        for index in range(5):
            buy_levels.append({
                'price': round(bid - index * 0.05, 2),
                'quantity': 100,
                'orders': 1,
            })
            sell_levels.append({
                'price': round(offer + index * 0.05, 2),
                'quantity': 100,
                'orders': 1,
            })
        return {
            'last_price': last_price if last_price is not None else offer,
            'average_price': 999.80,
            'previous_close': 995.00,
            'depth': {
                'buy': buy_levels,
                'sell': sell_levels,
            },
        }


class StandInParent:
    """Stands in for the plan order's parent, holding the caller's body.

    Attributes:
        body (dict): The caller's order body.
    """

    def __init__(self, transaction_type):
        """Builds the parent for an order of ten RELIANCE shares.

        Args:
            transaction_type (str): BUY or SELL.

        Returns:
            None: This method returns nothing.
        """
        self.body = {
            'instrument_id': INSTRUMENT_ID,
            'transaction_type': transaction_type,
            'order_type': 'LIMIT',
            'quantity': 10,
            'price': '1000.00',
        }


class StandInPlanOrder:
    """Stands in for the plan order, reading quotes with RELIANCE's tick size of 0.05 on the NSE.

    Attributes:
        parent (StandInParent): The parent, holding the caller's body.
    """

    def __init__(self, transaction_type='BUY'):
        """Builds the stand-in.

        Args:
            transaction_type (str): The side of the caller's body.

        Returns:
            None: This method returns nothing.
        """
        self.parent = StandInParent(transaction_type)

    def view(self, quotes, instrument_id=None):
        """One instrument's quote as a market view.

        Args:
            quotes (dict): Quotes by instrument id.
            instrument_id (str | None): The instrument, or None for RELIANCE.

        Returns:
            MarketView: The view.
        """
        wanted = instrument_id or INSTRUMENT_ID
        return MarketView(quotes.get(wanted), decimal.Decimal('0.05'))

    def trading_segment(self):
        """The segment RELIANCE trades on.

        Returns:
            str: `nse_equities`.
        """
        return 'nse_equities'


class EachMemberKeepsItsOwnCountExample:
    """Runs a group of two `double_last` conditions, on RELIANCE and on its future, through three ticks.

    Attributes:
        plan_order (StandInPlanOrder): The stand-in plan order.
        quotes (QuoteBuilder): Builds the ticks' quotes.
    """

    def __init__(self):
        """Builds the stand-ins.

        Returns:
            None: This method returns nothing.
        """
        self.plan_order = StandInPlanOrder()
        self.quotes = QuoteBuilder()

    def run(self):
        """Prints the group's answer and memory on each tick.

        Returns:
            None: This method returns nothing.
        """
        group = ConditionGroup(
            'all',
            [
                PriceCrossesCondition(decimal.Decimal('995'), None, 'last', None, 'double_last', None),
                PriceCrossesCondition(decimal.Decimal('1010'), 'at_or_above', 'last', FUTURE_ID, 'double_last', None),
                PriceCrossesCondition(decimal.Decimal('1011'), 'at_or_above', 'last', FUTURE_ID, 'none', None),
            ],
        )
        print(f'Watches: {group.instruments()}')
        memory = {}
        ticks = (
            (994.90, 1004.30),
            (994.90, 1010.30),
            (994.90, 1011.30),
        )
        for index, (reliance, future) in enumerate(ticks):
            quotes = {
                INSTRUMENT_ID: self.quotes.book_at(reliance - 0.05, reliance),
                FUTURE_ID: self.quotes.book_at(future - 0.2, future),
            }
            met = group.is_met(self.plan_order, memory, quotes, float(index), 'BUY', 'BUY')
            print(f'tick {index + 1}: RELIANCE {reliance}, future {future}: met {met}, memory {memory}')


if __name__ == '__main__':
    EachMemberKeepsItsOwnCountExample().run()
