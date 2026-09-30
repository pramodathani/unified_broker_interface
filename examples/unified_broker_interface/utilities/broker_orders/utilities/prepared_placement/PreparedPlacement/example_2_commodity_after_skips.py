"""Prepares a crude oil future at Zerodha after another broker was passed over, and shows the quantity in Zerodha's own terms.

The caller asks for 200 barrels of a crude oil future whose trusted contract size is 100 barrels a lot. Kotak is passed over first because it has no login in Redis; the placement records that in `skipped`. Zerodha counts MCX quantity in its own lot size, which its handle gives as 1, so `order_quantities` turns 200 barrels into 2, and `broker_quantity` on the prepared placement is what a freeze limit is compared against.

The request is built with `ZerodhaOrders.build_place_request` and never sent. The login and settings are made-up values, and the contract size decision is the one `test_runs/order_routes.py` stores for crude oil.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/prepared_placement/PreparedPlacement/example_2_commodity_after_skips.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.broker_orders.utilities.place_order_request import (
    PlaceOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.prepared_placement import (
    PreparedPlacement,
)
from unified_broker_interface.utilities.broker_orders.zerodha import (
    ZerodhaOrders,
)


class CommodityAfterSkipsExample:
    """Prepares a crude oil order at Zerodha and prints the placement's fields.

    Attributes:
        prepared (PreparedPlacement): The prepared order.
        units (int): The quantity the caller asked for, in barrels.
    """

    def __init__(self):
        """Validates the order, converts its quantity and prepares the placement.

        Returns:
            None: This method returns nothing.
        """
        order = PlaceOrderRequest({
            'instrument_id': '22222222-2222-5222-8222-000000000001',
            'transaction_type': 'SELL',
            'product': 'NRML',
            'order_type': 'LIMIT',
            'price': '6000',
            'quantity': 200,
        })
        self.units = order.quantity
        handle = {
            'broker_token': '569900',
            'order_symbol': 'CRUDEOIL26OCTFUT',
            'lot_size': 1.0,
            'tick_size': 1.0,
        }
        instrument = Instrument(
            order.instrument_id,
            {
                'segment': 'mcx_commodity_futures',
            },
            {
                'zerodha': handle,
            },
            {
                'units_per_lot': '100',
                'status': 'confirmed',
                'tradeable': True,
            },
        )
        broker_orders = ZerodhaOrders()
        quantity, disclosed_quantity = broker_orders.order_quantities(order, instrument, handle)
        broker_order = order.with_quantities(quantity, disclosed_quantity)
        login = {
            'access_token': 'example-access-token',
        }
        settings = {
            'api_key': 'example-api-key',
        }
        broker_request = broker_orders.build_place_request(broker_order, instrument, handle, login, settings)
        skipped = [
            {
                'broker': 'kotak',
                'reason': 'has no login in Redis',
            },
        ]
        self.prepared = PreparedPlacement(
            order.instrument_id,
            broker_orders,
            broker_request,
            skipped,
            identifier_sent=handle['order_symbol'],
            broker_quantity=quantity,
        )

    def run(self):
        """Prints the prepared placement's fields.

        Returns:
            None: This method returns nothing.
        """
        print(f'Broker: {self.prepared.broker_name}')
        print(f'Skipped: {self.prepared.skipped}')
        print(f'Caller asked for {self.units} barrels; request carries quantity {self.prepared.broker_quantity}')
        print(f'Identifier sent: {self.prepared.identifier_sent}')
        print(f'Request: {self.prepared.broker_request.shown()}')


if __name__ == '__main__':
    CommodityAfterSkipsExample().run()
