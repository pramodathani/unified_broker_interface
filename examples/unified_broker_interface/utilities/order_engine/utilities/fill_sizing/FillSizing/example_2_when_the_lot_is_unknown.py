"""Shows the lot the sizing falls back to when the broker's handle has none, has a bad one, or no broker has been chosen yet.

`FillSizing.lot_size` reads the lot from the handle of the broker the plan's orders go to, and takes one whenever that cannot be read, so the rounding never divides by nothing. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/fill_sizing/FillSizing/example_2_when_the_lot_is_unknown.py
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


class WhenTheLotIsUnknownExample:
    """Asks for the lot in four catalogues."""

    def run(self):
        """Prints each lot and what 130 rounds to with it.

        Returns:
            None: This method returns nothing.
        """
        sizing = FillSizing(True)
        cases = [
            (
                'a lot of 50',
                {
                    'dhan': {
                        'lot_size': '50',
                    },
                },
                'dhan',
            ),
            (
                'no lot published',
                {
                    'dhan': {},
                },
                'dhan',
            ),
            (
                'a lot that is not a number',
                {
                    'dhan': {
                        'lot_size': 'n/a',
                    },
                },
                'dhan',
            ),
            (
                'no broker chosen yet',
                {
                    'dhan': {
                        'lot_size': '50',
                    },
                },
                None,
            ),
        ]
        for label, handles, broker in cases:
            context = StandInContext(handles, broker)
            print(f'{label}: lot {sizing.lot_size(context)}, 130 rounds to {sizing.rounded(context, decimal.Decimal(130))}')


if __name__ == '__main__':
    WhenTheLotIsUnknownExample().run()
