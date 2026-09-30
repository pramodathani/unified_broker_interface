"""Checks quantities against lot sizes and prices against tick sizes, and rounds an engine-computed price to a tick.

Every broker's order handle for an instrument carries its `lot_size` and `tick_size`. The routes check a quantity against the chosen broker's lot size, and a currency or commodity quantity against the morning's trusted contract size. Prices are checked against the tick size most brokers agree on, so one broker with a stale master cannot make a valid price look wrong. When two sizes tie, nothing is checked.

`rounded_to_tick` is for prices the order engine works out itself, such as a midpoint, which usually fall between ticks. `BUY` rounds down and `SELL` rounds up, so the order rests rather than crossing the spread.

The handles are the shapes `test_runs/order_routes.py` builds. Nothing is sent.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/order_request/OrderRequest/example_2_lots_and_ticks.py
"""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    OrderRequest,
)


class LotsAndTicksExample:
    """Runs the lot and tick checks on a NIFTY option's handles.

    Attributes:
        order_request (OrderRequest): The request whose checks are used.
        handles (dict): Three brokers' order handles for the instrument.
    """

    def __init__(self):
        """Builds the request and the handles, one of which disagrees on the tick size.

        Returns:
            None: This method returns nothing.
        """
        self.order_request = OrderRequest()
        self.handles = {
            'zerodha': {
                'order_symbol': 'NIFTY26SEP25000CE',
                'lot_size': 75.0,
                'tick_size': 0.05,
            },
            'dhan': {
                'broker_token': '43210',
                'lot_size': 75.0,
                'tick_size': 0.05,
            },
            'fyers': {
                'order_symbol': 'NSE:NIFTY26SEP25000CE',
                'lot_size': 75.0,
                'tick_size': 0.1,
            },
        }

    def run(self):
        """Prints the result of each check.

        Returns:
            None: This method returns nothing.
        """
        zerodha_handle = self.handles['zerodha']
        print(f'150 units: {self.order_request.handle_lot_size_problem(150, zerodha_handle)}')
        print(f'100 units: {self.order_request.handle_lot_size_problem(100, zerodha_handle)}')
        crude_quantities = {
            'quantity': 300,
            'disclosed_quantity': 150,
        }
        problem = self.order_request.quantities_off_lot_problem(decimal.Decimal('100'), crude_quantities)
        print(f'Crude oil quantities against 100 barrels a lot: {problem}')
        agreed = self.order_request.agreed_tick_size(self.handles)
        print(f'Agreed tick size: {agreed}')
        prices = {
            'price': decimal.Decimal('120.05'),
            'trigger_price': decimal.Decimal('119.97'),
        }
        print(f'Price check: {self.order_request.prices_off_tick_problem(self.handles, prices)}')
        tied_handles = {
            'zerodha': self.handles['zerodha'],
            'fyers': self.handles['fyers'],
        }
        print(f'Agreed tick size when two brokers disagree: {self.order_request.agreed_tick_size(tied_handles)}')
        midpoint = decimal.Decimal('120.025')
        tick_size = decimal.Decimal('0.05')
        print(f'Midpoint {midpoint} for a buy: {self.order_request.rounded_to_tick(midpoint, tick_size, "BUY")}')
        print(f'Midpoint {midpoint} for a sell: {self.order_request.rounded_to_tick(midpoint, tick_size, "SELL")}')
        print(f'Midpoint {midpoint} to the nearest: {self.order_request.rounded_to_tick(midpoint, tick_size)}')
        try:
            self.order_request.rounded_to_tick(midpoint, decimal.Decimal('0'))
        except ValueError as error:
            print(f'Refused: {error}')


if __name__ == '__main__':
    LotsAndTicksExample().run()
