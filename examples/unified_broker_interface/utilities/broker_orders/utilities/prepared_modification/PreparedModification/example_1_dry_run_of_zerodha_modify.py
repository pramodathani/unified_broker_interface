"""Prepares a Zerodha modification that moves a stop-loss order's trigger, and answers a dry run from it.

`PUT /api/orders/modify` lays the caller's change over the stored order, builds the broker's modify request and wraps it in a `PreparedModification` together with the instrument it found for the order. With `dry_run` set it answers from `dry_run_answer`, which shows the request that would have been sent, and sends nothing. Kite is sent the order type every time, and the price and trigger price because an SL order takes both.

The stored order is the `MODSTOPLOSS` case from `test_runs/order_routes.py`. The login and settings are made-up values. Preparation time changes on every run, so only the names of the timings are printed.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/prepared_modification/PreparedModification/example_1_dry_run_of_zerodha_modify.py
"""

import json
import time

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.utilities.modify_order_request import (
    ModifyOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_modification import (
    OrderModification,
)
from unified_broker_interface.utilities.broker_orders.utilities.prepared_modification import (
    PreparedModification,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    StoredOrder,
)
from unified_broker_interface.utilities.broker_orders.zerodha import (
    ZerodhaOrders,
)


class DryRunOfZerodhaModifyExample:
    """Prepares the modification and prints its dry-run answer.

    Attributes:
        prepared (PreparedModification): The prepared modification.
    """

    def __init__(self):
        """Builds Zerodha's modify request for a stored stop-loss order.

        Returns:
            None: This method returns nothing.
        """
        broker_orders = ZerodhaOrders()
        stored_order = StoredOrder({
            'order': {
                'status': 'TRIGGER PENDING',
                'order_id': 'MODSTOPLOSS',
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'SL',
                'validity': 'DAY',
                'quantity': 10,
                'price': 2490.0,
                'trigger_price': 2495.0,
            },
            'data': {},
        })
        modify_request = ModifyOrderRequest(
            {
                'order_id': 'MODSTOPLOSS',
                'trigger_price': '2492.5',
                'dry_run': True,
            },
            werkzeug.datastructures.MultiDict(),
            [
                'zerodha',
            ],
        )
        modification = OrderModification(modify_request, stored_order)
        login = {
            'access_token': 'example-access-token',
        }
        settings = {
            'api_key': 'example-api-key',
        }
        broker_request = broker_orders.build_modify_request('MODSTOPLOSS', stored_order, modification, login, settings)
        self.prepared = PreparedModification(
            broker_orders,
            'MODSTOPLOSS',
            stored_order,
            '11111111-1111-5111-8111-000000000001',
            broker_request,
        )

    def run(self):
        """Prints the dry-run answer, with the timing values left out.

        Returns:
            None: This method returns nothing.
        """
        body, status = self.prepared.dry_run_answer(time.perf_counter())
        timings = sorted(body.pop('timing_ms'))
        print(f'HTTP {status}')
        print(json.dumps(body, indent=2, sort_keys=True))
        print(f'Timings reported: {timings}')


if __name__ == '__main__':
    DryRunOfZerodhaModifyExample().run()
