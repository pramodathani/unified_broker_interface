"""Prepares a cancel of an after-market Zerodha order and answers a dry run from it.

`DELETE /api/orders/cancel` checks the order, builds the broker's cancel request and wraps it in a `PreparedCancel`. With `dry_run` set it answers from `dry_run_answer`, which shows the request that would have been sent and the order's status before the cancel, and sends nothing. Zerodha's cancel URL carries the order's variety, which comes from the stored order's broker fields, so this after-market order is cancelled under `/orders/amo/`.

The answer includes how long preparation took, measured from the moment the request arrived. That number changes on every run, so the program prints only which timings the answer holds. The login and settings are made-up values.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/prepared_cancel/PreparedCancel/example_1_dry_run_of_zerodha_cancel.py
"""

import json
import time

from unified_broker_interface.utilities.broker_orders.utilities.prepared_cancel import (
    PreparedCancel,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    StoredOrder,
)
from unified_broker_interface.utilities.broker_orders.zerodha import (
    ZerodhaOrders,
)


class DryRunOfZerodhaCancelExample:
    """Prepares the cancel and prints its dry-run answer.

    Attributes:
        prepared (PreparedCancel): The prepared cancel.
    """

    def __init__(self):
        """Builds Zerodha's cancel request for a stored after-market order.

        Returns:
            None: This method returns nothing.
        """
        broker_orders = ZerodhaOrders()
        stored_order = StoredOrder({
            'order': {
                'status': 'OPEN',
            },
            'data': {
                'variety': 'amo',
            },
        })
        login = {
            'access_token': 'example-access-token',
        }
        settings = {
            'api_key': 'example-api-key',
        }
        broker_request = broker_orders.build_cancel_request('250915000000011', stored_order, login, settings)
        self.prepared = PreparedCancel(broker_orders, '250915000000011', stored_order, broker_request)

    def run(self):
        """Prints the dry-run answer, with the timing values left out.

        Returns:
            None: This method returns nothing.
        """
        started_at = time.perf_counter()
        body, status = self.prepared.dry_run_answer(started_at)
        timings = sorted(body.pop('timing_ms'))
        print(f'HTTP {status}')
        print(json.dumps(body, indent=2, sort_keys=True))
        print(f'Timings reported: {timings}')
        print(f'Engine command: {self.prepared.engine_command}')


if __name__ == '__main__':
    DryRunOfZerodhaCancelExample().run()
