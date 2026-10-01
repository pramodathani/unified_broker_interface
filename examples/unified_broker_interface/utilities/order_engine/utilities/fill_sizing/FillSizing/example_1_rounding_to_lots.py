"""Rounds a few wanted sizes to whole lots of 75, and to whole units, as every Then child's sizing does.

`FillSizing.rounded` rounds half up: 37.5 is half a lot, so it rounds to one lot of 75, and 37 rounds to none. Without `whole_lots` it rounds to whole units. `check` refuses nothing for the base sizing; `FillDelta` overrides it. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/fill_sizing/FillSizing/example_1_rounding_to_lots.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.fill_sizing import (
    FillSizing,
)


class StandInInstrument:
    """Stands in for the order's instrument in the catalogue.

    Attributes:
        handles (dict): Each broker's handle, with its lot size.
    """

    def __init__(self, handles):
        """Builds the instrument.

        Args:
            handles (dict): Each broker's handle.

        Returns:
            None: This method returns nothing.
        """
        self.handles = handles


class StandInPlacement:
    """Stands in for the placement, which reads the catalogue.

    Attributes:
        instrument (StandInInstrument): The instrument.
    """

    def __init__(self, handles):
        """Builds the placement.

        Args:
            handles (dict): Each broker's handle.

        Returns:
            None: This method returns nothing.
        """
        self.instrument = StandInInstrument(handles)

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
        return self.instrument, None, None


class StandInContext:
    """Stands in for the order's view of the plan order.

    Attributes:
        instrument_id (str): The order's instrument.
        placement (StandInPlacement): The catalogue.
        broker (str | None): The broker the plan's orders went to.
    """

    def __init__(self, handles, broker):
        """Builds the context.

        Args:
            handles (dict): Each broker's handle.
            broker (str | None): The broker the plan's orders went to.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = 'NIFTY FUTURE'
        self.placement = StandInPlacement(handles)
        self.broker = broker

    def chosen_broker(self):
        """The broker the plan's orders went to.

        Returns:
            str | None: The broker.
        """
        return self.broker


class RoundingToLotsExample:
    """Rounds the same sizes both ways."""

    def run(self):
        """Prints each rounding.

        Returns:
            None: This method returns nothing.
        """
        context = StandInContext(
            {
                'zerodha': {
                    'lot_size': 75,
                },
            },
            'zerodha',
        )
        in_lots = FillSizing(True)
        in_units = FillSizing(False)
        print(f'check: {in_lots.check(context)}')
        print(f'lot: {in_lots.lot_size(context)}')
        wanted_sizes = (
            '37',
            '37.5',
            '112.4',
            '112.5',
            '900.2',
        )
        for wanted in wanted_sizes:
            amount = decimal.Decimal(wanted)
            print(f'{wanted}: {in_lots.rounded(context, amount)} in lots, {in_units.rounded(context, amount)} in units')


if __name__ == '__main__':
    RoundingToLotsExample().run()
