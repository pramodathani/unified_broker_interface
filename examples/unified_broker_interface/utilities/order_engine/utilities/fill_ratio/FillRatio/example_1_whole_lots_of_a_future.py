"""Sizes a hedge at half of what a stock entry filled, in whole lots of 250, as the entry fills.

`FillRatio.scaled` is `ratio × filled`, rounded to the nearest whole lot at the broker the plan's orders go to, from `lot_size`. Until half a lot is wanted the hedge is nothing. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/fill_ratio/FillRatio/example_1_whole_lots_of_a_future.py
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


class WholeLotsOfAFutureExample:
    """Prints a hedge's size as its entry fills."""

    def run(self):
        """Prints each size.

        Returns:
            None: This method returns nothing.
        """
        ratio = FillRatio(decimal.Decimal('0.5'), True)
        context = StandInContext('flattrade')
        print(f'Lot: {ratio.lot_size(context)}')
        for filled in (100, 300, 600, 1000):
            print(f'{filled} filled: hedge {ratio.scaled(context, filled)}')
        print(f'As a dry run shows it: {ratio.described()}')


if __name__ == '__main__':
    WholeLotsOfAFutureExample().run()
