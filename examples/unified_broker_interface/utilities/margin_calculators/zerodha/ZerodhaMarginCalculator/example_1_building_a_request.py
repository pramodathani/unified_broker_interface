"""Builds the request Zerodha's margin calculator is sent for one lot of NIFTY futures sold, and shows how it counts a lot of crude oil.

A `ZerodhaMarginCalculator` asks Kite what an order needs, using the login every other process uses; it never logs in and places nothing. Building a request is kept apart from sending it, so this program builds one without any network, from a stand-in login and settings and the NIFTY October future's real order handle of 2026-09-30. The session headers, which carry the token, are not printed.

`takes` says whether Zerodha can be asked about a leg at all: it must trade the market and have a handle for the instrument. `broker_quantity` converts the leg's units into Zerodha's own terms, which for crude oil is lots, so 100 barrels is 1.

Run it from the project root:

    python examples/unified_broker_interface/utilities/margin_calculators/zerodha/ZerodhaMarginCalculator/example_1_building_a_request.py
"""

import decimal
import json

from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.margin_calculators.zerodha import (
    ZerodhaMarginCalculator,
)
from unified_broker_interface.utilities.margin_calculators.utilities.reference_leg import (
    ReferenceLeg,
)

STAND_IN_LOGIN = {
    'access_token': 'stand-in-token',
    'sid': 'stand-in-session',
}
STAND_IN_SETTINGS = {
    'api_key': 'stand-in-key',
    'app_id': 'STANDIN-100',
    'client_id': '1000000001',
    'username': 'STANDIN1',
    'ucc_code': 'STANDIN1',
}


class BuildingARequestExample:
    """Builds Zerodha's request for a sold NIFTY future and checks a crude oil future.

    Attributes:
        calculator (ZerodhaMarginCalculator): The calculator, with stand-in credentials.
        future_leg (ReferenceLeg): One lot of NIFTY futures sold.
        crude_leg (ReferenceLeg): One lot of crude oil futures bought.
    """

    def __init__(self):
        """Builds the calculator and the two legs.

        Returns:
            None: This method returns nothing.
        """
        self.calculator = ZerodhaMarginCalculator(STAND_IN_LOGIN, STAND_IN_SETTINGS)
        future_identity = {
            'segment': 'nse_equity_index_futures',
            'shape': 'future',
            'underlying_symbol': 'NIFTY',
            'expiry_date': '2026-10-27',
        }
        future_handles = {
            'zerodha': {
                "broker_token": "12468226",
                "order_symbol": "NIFTY26OCTFUT",
                "lot_size": "65.0",
                "tick_size": "0.1"
            },
        }
        future = Instrument('28312010-2d68-5c8d-8b42-a66bc13a7816', future_identity, future_handles)
        self.future_leg = ReferenceLeg('NIFTY future sold', future, 'SELL', 'NRML', 65, decimal.Decimal('22833.7'))
        crude_identity = {
            'segment': 'mcx_commodity_futures',
            'shape': 'future',
            'underlying_symbol': 'CRUDEOIL',
            'expiry_date': '2026-10-19',
        }
        crude_handles = {
            'zerodha': {
                "broker_token": "145894407",
                "order_symbol": "CRUDEOIL26OCTFUT",
                "lot_size": "1.0",
                "tick_size": "1.0"
            },
        }
        contract_size = {
            'units_per_lot': '100',
            'status': 'confirmed',
            'tradeable': True,
        }
        crude = Instrument('3214cb7e-937a-5edb-9239-f178e658fc89', crude_identity, crude_handles, contract_size)
        self.crude_leg = ReferenceLeg('crude oil future bought', crude, 'BUY', 'NRML', 100, decimal.Decimal('8618'))

    def run(self):
        """Prints the request's method, address and body, then what Zerodha makes of the crude oil leg.

        Returns:
            None: This method returns nothing.
        """
        request = self.calculator.build_order_request(self.future_leg)
        print(f'{request.method} {request.url}')
        if request.params:
            print(f'Query: {request.params}')
        if request.json_body is not None:
            print(f'JSON body: {json.dumps(request.json_body, indent=2)}')
        else:
            print(f'Form body: {request.data}')
        print(f'Takes the NIFTY future: {self.calculator.takes(self.future_leg)}, quantity {self.calculator.broker_quantity(self.future_leg)}')
        takes_crude = self.calculator.takes(self.crude_leg)
        print(f'Takes crude oil: {takes_crude}')
        if takes_crude:
            print(f'Crude oil quantity for 100 barrels: {self.calculator.broker_quantity(self.crude_leg)}')
        print(f'Prices baskets: {self.calculator.TAKES_BASKETS}')
        basket_request = self.calculator.build_basket_request([self.future_leg, self.future_leg])
        print(f'A basket of two goes to {basket_request.url}')
        print(f'kite_order names the instrument tradingsymbol = {self.calculator.kite_order(self.future_leg)['tradingsymbol']!r}')
        print(f'Header names from headers: {sorted(self.calculator.headers())}')


if __name__ == '__main__':
    BuildingARequestExample().run()
