"""Shows which positions three close orders would read: the order's own instrument, a named list, and every instrument on a product.

`PositionQuantity.product_of` is the product given, or the body's product turned into the name positions are held under, so `MIS` is `intraday`. `wanted_instruments` is the order's own instrument by default, the named `instrument_ids`, or None, meaning every instrument, for a square off. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/position_quantity/PositionQuantity/example_1_which_positions.py
"""

from unified_broker_interface.utilities.order_engine.utilities.position_quantity import (
    PositionQuantity,
)


class StandInContext:
    """Stands in for an order's view of the plan order.

    Attributes:
        instrument_id (str): The order's instrument.
        body (dict): The order's body.
    """

    def __init__(self):
        """Builds a context for an intraday order on RELIANCE.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = 'RELIANCE'
        self.body = {
            'product': 'MIS',
        }


class WhichPositionsExample:
    """Prints which positions each close order reads."""

    def run(self):
        """Prints a line per close order.

        Returns:
            None: This method returns nothing.
        """
        context = StandInContext()
        close_on_trigger = PositionQuantity(None, None, False, 1, True)
        named = PositionQuantity('delivery', ['INFY', 'TCS'], False, 1, True)
        square_off = PositionQuantity('intraday', None, True, 1, True)
        for name, quantity in (('close on trigger', close_on_trigger), ('named', named), ('square off', square_off)):
            instruments = quantity.wanted_instruments(context)
            if instruments is not None:
                instruments = sorted(instruments)
            print(f'{name}: product {quantity.product_of(context)}, instruments {instruments}')
        print(f'A stop and reverse that doubles: {PositionQuantity(None, None, False, 2, True).described()}')


if __name__ == '__main__':
    WhichPositionsExample().run()
