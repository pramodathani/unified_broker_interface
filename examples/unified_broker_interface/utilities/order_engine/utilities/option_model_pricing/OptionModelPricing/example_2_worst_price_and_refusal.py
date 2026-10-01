"""Shows a volatility order held at the worst price the caller gave, the first order it sends, and an order on something that is not an option.

The option here expires in 2099, so its premium is far above the caller's price whatever day this runs, and the output does not change.

The body's own price is the most a buy pays, so a model premium above it is held at it. `priced_body` sends the premium for the index's price now and remembers that price as the start. `prepared_memory` refuses an instrument the catalogue does not describe as an option. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/option_model_pricing/OptionModelPricing/example_2_worst_price_and_refusal.py
"""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.option_model_pricing import (
    OptionModelPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)


OPTION_ID = '11111111-1111-5111-8111-000000000003'
INDEX_ID = '11111111-1111-5111-8111-000000000010'


class StandInInstrument:
    """Stands in for an instrument as the catalogue describes it.

    Attributes:
        identity (dict): What the catalogue says the instrument is.
        bare_segment (str): Its segment, without the exchange.
    """

    def __init__(self, identity, bare_segment):
        """Builds the instrument.

        Args:
            identity (dict): What the catalogue says the instrument is.
            bare_segment (str): Its segment.

        Returns:
            None: This method returns nothing.
        """
        self.identity = identity
        self.bare_segment = bare_segment


class StandInPlacement:
    """Stands in for the engine's placement, which reads the catalogue.

    Attributes:
        instruments (dict): Each instrument id to its stand-in.
    """

    def __init__(self):
        """Builds a catalogue of a Nifty call and the index.

        Returns:
            None: This method returns nothing.
        """
        self.instruments = {
            OPTION_ID: StandInInstrument(
                {
                    'option_type': 'CE',
                    'strike_price': 25000,
                    'expiry_date': '2026-09-29',
                },
                'equity_index_options',
            ),
            INDEX_ID: StandInInstrument(
                {},
                'indices',
            ),
        }

    def market_context(self, instrument_id, with_quote, with_depth):
        """The instrument, as the engine's placement answers it.

        Args:
            instrument_id (str): The instrument.
            with_quote (bool): Unused.
            with_depth (bool): Unused.

        Returns:
            tuple: The instrument and two unused values.
        """
        del with_quote, with_depth
        return self.instruments[instrument_id], None, None


class StandInParent:
    """Stands in for a plan order's parent.

    Attributes:
        instrument_id (str): The instrument the order trades.
        body (dict): The caller's body.
    """

    def __init__(self, instrument_id, body):
        """Builds the parent.

        Args:
            instrument_id (str): The instrument the order trades.
            body (dict): The caller's body.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = instrument_id
        self.body = body


class StandInPlanOrder:
    """Stands in for the plan order a pricing is asked about.

    Attributes:
        parent (StandInParent): The parent.
        placement (StandInPlacement): The catalogue.
        instrument_id (str): The instrument the order trades.
        body (dict): The caller's body.
    """

    def __init__(self, instrument_id, body):
        """Builds the stand-in.

        Args:
            instrument_id (str): The instrument the order trades.
            body (dict): The caller's body.

        Returns:
            None: This method returns nothing.
        """
        self.parent = StandInParent(instrument_id, body)
        self.placement = StandInPlacement()
        self.instrument_id = instrument_id
        self.body = body

    def tick_size(self):
        """The order's tick size, five paise.

        Returns:
            decimal.Decimal: The tick size.
        """
        return decimal.Decimal('0.05')

    def view(self, quotes, instrument_id=None):
        """The market for an instrument, the order's own by default.

        Args:
            quotes (dict): The quotes, by instrument id.
            instrument_id (str | None): The instrument, or None for the order's own.

        Returns:
            MarketView: The view.
        """
        wanted = instrument_id or self.parent.instrument_id
        return MarketView(quotes.get(wanted), self.tick_size())


class QuoteMaker:
    """Builds quotes and resting orders."""

    def index_at(self, price):
        """The quotes a tick carries with the index at a price.

        Args:
            price (float): The index's last price.

        Returns:
            dict: The quotes, by instrument id.
        """
        return {
            INDEX_ID: {
                'last_price': price,
            },
        }

    def resting(self, side, price):
        """A resting broker order.

        Args:
            side (str): BUY or SELL.
            price (float): Its limit.

        Returns:
            OrderLeg: The leg.
        """
        leg = OrderLeg('parent-1:1', 'root')
        leg.transaction_type = side
        leg.price = price
        leg.quantity = 75
        leg.state = 'acknowledged'
        return leg


class WorstPriceAndRefusalExample:
    """Prints a held premium, a first order and a refusal."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        pricing = OptionModelPricing(INDEX_ID, decimal.Decimal('12.5'), decimal.Decimal('6.5'), None, None, 1)
        plan_order = StandInPlanOrder(OPTION_ID, {'order_type': 'LIMIT', 'price': 150})
        plan_order.placement.instruments[OPTION_ID].identity['expiry_date'] = '2099-12-31'
        memory = pricing.prepared_memory(plan_order)
        print(f'With a worst price of 150: {pricing.premium(plan_order, memory, "BUY", decimal.Decimal("25000"), {}, 1790137800.0)}')
        body = pricing.priced_body(plan_order, {'order_type': 'LIMIT', 'price': 150}, 'BUY', QuoteMaker().index_at(25000), memory)
        print(f'The first order is a {body["order_type"]} at {body["price"]}, remembering the index at {memory["watched_start"]}')
        print(f'The reason it gives: {pricing.reason(decimal.Decimal("25100"), decimal.Decimal("150"))}')
        index_order = StandInPlanOrder('11111111-1111-5111-8111-000000000099', {'order_type': 'LIMIT', 'price': 150})
        index_order.placement.instruments['11111111-1111-5111-8111-000000000099'] = StandInInstrument({}, 'equity')
        try:
            pricing.prepared_memory(index_order)
        except RefusedRequestError as refusal:
            print(f'On a share: {refusal.status} {refusal.body["error"]}')
        print(f'As a dry run shows it: {pricing.described()}')


if __name__ == '__main__':
    WorstPriceAndRefusalExample().run()
