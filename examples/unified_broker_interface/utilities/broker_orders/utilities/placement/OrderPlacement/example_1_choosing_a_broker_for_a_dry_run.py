"""Offers one order to the brokers in the selector's order, passes over one that cannot take it, and answers a dry run from the broker chosen.

`OrderPlacement` is the half of placing an order that reads no store: the order engine reads Redis and hands in every broker's login and settings as text, and the placement ranks the brokers, asks each in turn whether it can take the order, builds the chosen broker's request and answers. This program sets the selector to `fixed_priority` with Dhan first and Zerodha second, in the loaded configuration rather than in `.env`, because that selector needs no Redis replies.

Dhan holds a login but its settings lack `client_id`, so it is passed over with that reason; Zerodha is chosen. Every other broker has no login at all. The logins and settings are made-up values in the shapes Redis holds, and nothing is sent: the dry-run answer is printed instead. Preparation time changes on every run, so only the names of the timings are printed.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/placement/OrderPlacement/example_1_choosing_a_broker_for_a_dry_run.py
"""

import json
import logging
import time

from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.broker_orders.utilities.place_order_request import (
    PlaceOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.placement import (
    OrderPlacement,
)
from utilities.configurations import api_configuration


class ChoosingABrokerForADryRunExample:
    """Prepares one order and prints how the broker was chosen.

    Attributes:
        placement (OrderPlacement): The placement.
        order (PlaceOrderRequest): The validated order.
        instrument (Instrument): RELIANCE on the NSE, with Dhan's and Zerodha's handles.
        login_texts (list): Every broker's login as Redis holds it, in `broker_names` order.
        settings_texts (list): Every broker's settings as Redis holds them, in `broker_names` order.
    """

    def __init__(self):
        """Configures the selector and builds the placement, the order and the texts Redis would hold.

        Returns:
            None: This method returns nothing.
        """
        api_configuration['order_broker_selector'] = 'fixed_priority'
        api_configuration['order_broker_priority'] = [
            'dhan',
            'zerodha',
        ]
        api_configuration['order_excluded_brokers'] = [
            'wisdom_capital',
        ]
        api_configuration['order_warm_brokers'] = []
        self.placement = OrderPlacement(logging.getLogger('example'), 1)
        self.order = PlaceOrderRequest({
            'instrument_id': '11111111-1111-5111-8111-000000000001',
            'transaction_type': 'BUY',
            'product': 'MIS',
            'order_type': 'LIMIT',
            'price': '2500.10',
            'quantity': 10,
            'tag': 'swing01',
            'dry_run': True,
        })
        self.instrument = Instrument(
            self.order.instrument_id,
            {
                'segment': 'nse_equities',
            },
            {
                'dhan': {
                    'broker_token': '2885',
                    'order_symbol': 'RELIANCE',
                    'lot_size': 1.0,
                    'tick_size': 0.1,
                },
                'zerodha': {
                    'broker_token': '738561',
                    'order_symbol': 'RELIANCE',
                    'lot_size': 1.0,
                    'tick_size': 0.1,
                },
            },
        )
        logins = {
            'dhan': '{"access_token": "example-dhan-token"}',
            'zerodha': '{"access_token": "example-zerodha-token"}',
        }
        settings = {
            'dhan': '{}',
            'zerodha': '{"api_key": "example-api-key"}',
        }
        self.login_texts = []
        self.settings_texts = []
        for broker_name in self.placement.broker_names:
            self.login_texts.append(logins.get(broker_name))
            self.settings_texts.append(settings.get(broker_name))

    def run(self):
        """Prints the rotation, the choice and the dry-run answer.

        Returns:
            None: This method returns nothing.
        """
        print(f'Selector: {self.placement.broker_selector.NAME}')
        rotation = self.placement.rotation()
        print(f'Rotation: {rotation}')
        self.placement.check_contract_size(self.order, self.instrument)
        print('Contract size check: an equity needs none')
        ranked = self.placement.broker_selector.ranked_brokers(self.order, self.instrument, rotation, [])
        broker_orders, skipped = self.placement.choose_broker(self.order, self.instrument, rotation, ranked, self.login_texts, self.settings_texts)
        print(f'choose_broker picked {broker_orders.BROKER_NAME}, after passing over {len(skipped)} brokers:')
        for passed_over in skipped:
            print(f'  {passed_over["broker"]}: {passed_over["reason"]}')
        prepared = self.placement.prepare(self.order, self.instrument, rotation, [], self.login_texts, self.settings_texts)
        body, status = self.placement.dry_run_answer(prepared, time.perf_counter())
        timings = sorted(body.pop('timing_ms'))
        print(f'Dry run answered with HTTP {status}:')
        print(json.dumps(body, indent=2, sort_keys=True))
        print(f'Timings reported: {timings}')


if __name__ == '__main__':
    ChoosingABrokerForADryRunExample().run()
