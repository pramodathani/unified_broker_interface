"""Joins a time condition and a price condition with `all`, and then with `any`, and asks both groups through the morning.

A `ConditionGroup` is how a plan order waits for several things at once: `all` holds only when every member does, and `any` holds as soon as one does. This is what a plan gets when it names both the `scheduled` and the `market_if_touched` presets: the order waits until after the time and until the price has been touched. Each member keeps its own memory under its position in the group.

The engine's clock is replaced, in the `time_condition` module, with a stand-in stopped at 09:30 on Thursday 1 October 2026, and a small stand-in plays the plan order. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/condition_group/ConditionGroup/example_1_all_needs_every_member.py
"""

import datetime
import decimal

from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities import (
    time_condition,
)
from unified_broker_interface.utilities.order_engine.utilities.condition_group import (
    ConditionGroup,
)
from unified_broker_interface.utilities.order_engine.utilities.moments import (
    INDIA,
    Moments,
)
from unified_broker_interface.utilities.order_engine.utilities.price_crosses_condition import (
    PriceCrossesCondition,
)
from unified_broker_interface.utilities.order_engine.utilities.time_condition import (
    TimeCondition,
)

ASKED_AT = datetime.datetime(2026, 10, 1, 9, 30, tzinfo=INDIA)


class FixedMoments(Moments):
    """The engine's clock, stopped at 09:30 on Thursday 1 October 2026, a trading day."""

    def now(self):
        """The fixed moment.

        Returns:
            datetime.datetime: 09:30 on 1 October 2026, in India.
        """
        return ASKED_AT


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


class AllNeedsEveryMemberExample:
    """Asks an `all` group and an `any` group the same questions at four moments.

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

    def group(self, joiner):
        """A group of `time_after 10:00` and a buy waiting for 995.

        Args:
            joiner (str): `all` or `any`.

        Returns:
            ConditionGroup: The group.
        """
        return ConditionGroup(
            joiner,
            [
                TimeCondition('time_after', '10:00'),
                PriceCrossesCondition(decimal.Decimal('995'), None, 'last', None, 'none', None),
            ],
        )

    def run(self):
        """Prints each group's answer at each moment.

        Returns:
            None: This method returns nothing.
        """
        time_condition.Moments = FixedMoments
        both = self.group('all')
        either = self.group('any')
        both_memory = {}
        either_memory = {}
        both.prepare(self.plan_order, both_memory)
        either.prepare(self.plan_order, either_memory)
        print(f'Reads quotes: {both.needs_prices()}, watches: {both.instruments()}')
        print(f'Memory after preparing: {sorted(both_memory)}')
        touched = self.quotes.book_at(994.85, 994.90)
        steady = self.quotes.book_at(1000.00, 1000.05)
        for hour, minute, quote, label in ((9, 45, steady, 'steady'), (9, 50, touched, 'touched'), (10, 5, steady, 'steady'), (10, 10, touched, 'touched')):
            moment = datetime.datetime(2026, 10, 1, hour, minute, tzinfo=INDIA).timestamp()
            quotes = {
                INSTRUMENT_ID: quote,
            }
            all_met = both.is_met(self.plan_order, both_memory, quotes, moment, 'BUY', 'BUY')
            any_met = either.is_met(self.plan_order, either_memory, quotes, moment, 'BUY', 'BUY')
            print(f'{hour:02d}:{minute:02d}, price {label}: all {all_met}, any {any_met}')
        print(f'As a dry run shows it: {both.described()}')


if __name__ == '__main__':
    AllNeedsEveryMemberExample().run()
