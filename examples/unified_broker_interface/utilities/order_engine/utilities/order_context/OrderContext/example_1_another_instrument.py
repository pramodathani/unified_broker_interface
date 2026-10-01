"""Shows an order of a plan that trades an instrument other than the parent's, as its pricing sees the plan.

`OrderContext` answers the tick size and the market for the order's own instrument, from the tick sizes the plan remembered, and reads the segment from the catalogue. A broker order it places carries its instrument, while cancels, reductions and reading an order go to the plan order as they are. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/order_context/OrderContext/example_1_another_instrument.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.order_context import (
    OrderContext,
)


PARENTS_INSTRUMENT = '11111111-1111-5111-8111-000000000001'
OTHER_INSTRUMENT = '11111111-1111-5111-8111-000000000002'


class StandInParent:
    """Stands in for the plan order's parent.

    Attributes:
        instrument_id (str): The parent's instrument.
        body (dict): The caller's body.
        parameters (dict): The parent's parameters, with the other instrument's tick size.
    """

    def __init__(self):
        """Builds the parent.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = PARENTS_INSTRUMENT
        self.body = {
            'transaction_type': 'BUY',
            'quantity': 10,
            'price': 1000,
        }
        self.parameters = {
            'tick_sizes': {
                OTHER_INSTRUMENT: '0.01',
            },
        }


class StandInInstrument:
    """Stands in for an instrument in the catalogue.

    Attributes:
        segment (str): Its exchange-prefixed segment.
    """

    def __init__(self, segment):
        """Builds the instrument.

        Args:
            segment (str): Its segment.

        Returns:
            None: This method returns nothing.
        """
        self.segment = segment


class StandInPlacement:
    """Stands in for the placement, which reads the catalogue."""

    def market_context(self, instrument_id, with_quote, with_depth):
        """The instrument, as the placement answers it.

        Args:
            instrument_id (str): The instrument.
            with_quote (bool): Unused.
            with_depth (bool): Unused.

        Returns:
            tuple: The instrument and two unused values.
        """
        del instrument_id, with_quote, with_depth
        return StandInInstrument('mcx_commodity_futures'), None, None


class StandInPlanOrder:
    """Stands in for the plan order, noting every request handed to it.

    Attributes:
        parent (StandInParent): The parent.
        placement (StandInPlacement): The catalogue.
        requests (list): Every request, in order.
    """

    def __init__(self):
        """Builds the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.parent = StandInParent()
        self.placement = StandInPlacement()
        self.requests = []

    def tick_size(self):
        """The parent's tick size.

        Returns:
            decimal.Decimal: 0.05.
        """
        return decimal.Decimal('0.05')

    def view(self, quotes, instrument_id=None):
        """The parent's market.

        Args:
            quotes (dict): The quotes, by instrument id.
            instrument_id (str | None): The instrument, or None for the parent's.

        Returns:
            MarketView: The view.
        """
        return MarketView(quotes.get(instrument_id or PARENTS_INSTRUMENT), self.tick_size())

    def trading_segment(self):
        """The parent's segment.

        Returns:
            str: `nse_equity`.
        """
        return 'nse_equity'

    def place_leg(self, role, order, started_at, broker_name=None, instrument_id=None, leg_group=None):
        """Notes a placement.

        Args:
            role (str): The leg's role.
            order (dict): The order.
            started_at (float | None): Unused.
            broker_name (str | None): The broker.
            instrument_id (str | None): The instrument, or None for the parent's.
            leg_group (object | None): Unused.

        Returns:
            tuple: An answer, a status and no leg.
        """
        del started_at, leg_group
        self.requests.append(f'place {role} on {instrument_id or "the parent\'s instrument"} at {broker_name}')
        return {'outcome': 'accepted'}, 200, None

    def cancel_leg(self, leg, reason):
        """Notes a cancel.

        Args:
            leg (str): The leg.
            reason (str): Why.

        Returns:
            bool: True.
        """
        self.requests.append(f'cancel {leg}: {reason}')
        return True

    def reduce_leg(self, leg, quantity, reason):
        """Notes a reduction.

        Args:
            leg (str): The leg.
            quantity (int): Its new total.
            reason (str): Why.

        Returns:
            bool: True.
        """
        self.requests.append(f'reduce {leg} to {quantity}: {reason}')
        return True

    def read_order(self, body):
        """The body as an order, kept as it is here.

        Args:
            body (dict): The body.

        Returns:
            dict: The body.
        """
        return body

    def chosen_broker(self):
        """The broker the plan's orders go to.

        Returns:
            str: `zerodha`.
        """
        return 'zerodha'


class AnotherInstrumentExample:
    """Prints what a context on another instrument answers."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder()
        body = dict(plan_order.parent.body, quantity=5)
        context = OrderContext(plan_order, OTHER_INSTRUMENT, body)
        quotes = {
            OTHER_INSTRUMENT: {
                'last_price': 250.004,
            },
        }
        print(f'The parent\'s instrument: {context.is_parents_instrument()}, tick size {context.tick_size()}, the parent\'s tick size {context.tick_size(PARENTS_INSTRUMENT)}')
        print(f'Last price on its tick: {context.view(quotes).last()}, segment {context.trading_segment()}, body quantity {context.body["quantity"]}')
        context.place_leg('root.children.1', body, None, 'zerodha')
        context.cancel_leg('leg-1', 'the plan was cancelled')
        context.reduce_leg('leg-2', 3, 'a sibling filled')
        print(f'Reads an order as {context.read_order({"quantity": 5})}, chosen broker {context.chosen_broker()}, placement {type(context.placement).__name__}, parent instrument {context.parent.instrument_id}')
        for request in plan_order.requests:
            print(f'  {request}')


if __name__ == '__main__':
    AnotherInstrumentExample().run()
