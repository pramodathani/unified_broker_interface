"""Shows a ratio without whole lots, which rounds to the nearest unit, and a lot read before any broker is chosen, which is one.

Without `whole_lots`, `FillRatio.scaled` rounds half up to a whole unit. With no broker chosen yet the catalogue gives no lot, so `lot_size` is one. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/fill_ratio/FillRatio/example_2_without_lots.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.fill_ratio import (
    FillRatio,
)


class StandInInstrument:
    """Stands in for the hedge instrument in the catalogue.

    Attributes:
        handles (dict): Each broker's handle, with its lot size.
    """

    def __init__(self):
        """Builds a future traded in lots of 250 at Flattrade.

        Returns:
            None: This method returns nothing.
        """
        self.handles = {
            'flattrade': {
                'lot_size': '250',
            },
        }


class StandInPlacement:
    """Stands in for the placement, which reads the catalogue."""

    def market_context(self, instrument_id, with_quote, with_depth):
        """The instrument.

        Args:
            instrument_id (str): Unused.
            with_quote (bool): Unused.
            with_depth (bool): Unused.

        Returns:
            tuple: The instrument and two unused values.
        """
        del instrument_id, with_quote, with_depth
        return StandInInstrument(), None, None


class StandInContext:
    """Stands in for the hedge order's view of the plan order.

    Attributes:
        instrument_id (str): The hedge instrument.
        placement (StandInPlacement): The catalogue.
        broker (str | None): The broker the plan's orders went to.
    """

    def __init__(self, broker):
        """Builds the context.

        Args:
            broker (str | None): The broker the plan's orders went to.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = 'RELIANCE FUTURE'
        self.placement = StandInPlacement()
        self.broker = broker

    def chosen_broker(self):
        """The broker the plan's orders went to.

        Returns:
            str | None: The broker.
        """
        return self.broker


class WithoutLotsExample:
    """Prints sizes without lots."""

    def run(self):
        """Prints each size.

        Returns:
            None: This method returns nothing.
        """
        ratio = FillRatio(decimal.Decimal('1.5'), False)
        context = StandInContext(None)
        for filled in (3, 7):
            print(f'{filled} filled: {ratio.scaled(context, filled)}')
        print(f'Lot before a broker is chosen: {ratio.lot_size(context)}')


if __name__ == '__main__':
    WithoutLotsExample().run()
