"""Chooses the broker for a new order at intake, then makes one worker thread's legs go to it.

With broker lanes, the engine's intake decides which broker a new parent will use before it hands the parent to that broker's lane. `assign_broker` makes that choice exactly as a placement would, with the configured selector, but sends nothing. The worker thread that then runs the parent calls `use_assignment`, so every leg it prepares goes to that broker without asking the selector again, and `clear_assignment` when it is done.

The assignment is held separately for each thread, in a `BrokerAssignment`, so one worker's broker never leaks into another's. The program shows this by preparing the same order on a worker thread that holds an assignment and on the main thread that holds none. It also shows the two cases in which intake does not ask the selector: a body that names its own broker, as flatten's closing orders do, keeps that broker, and a body that does not validate gets no broker, so the order type chooses one when it runs. Finally, an assignment to a broker that cannot take the leg is dropped and the selector chooses again.

Configuration is set in the program: the `fixed_priority` selector with Zerodha preferred before Dhan, no broker excluded and no connection warming. Zerodha has no login in Redis, so intake passes over it. Redis is the in-memory `FakeRedis` from `test_runs/redis_stand_ins.py`, filled with one mapped instrument and the brokers' logins and settings. Nothing is sent to any broker, because only `prepare` is called.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/engine_placement/EnginePlacement/example_2_intake_assigns_the_broker.py
"""

import json
import logging
import threading

from test_runs.redis_stand_ins import FakeRedis
from unified_broker_interface.utilities.broker_orders.utilities.place_order_request import (
    PlaceOrderRequest,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_placement import (
    EnginePlacement,
)
from utilities.configurations import api_configuration

MAPPING_DATE = '2026-09-30'
INFOSYS_ID = '6d1f3a52-8b0e-5c47-9a21-3e4f5b6c7d80'


class IntakeAssignsTheBrokerExample:
    """Assigns a broker at intake and prepares legs on a worker thread and on the main thread.

    Attributes:
        cache (FakeRedis): The in-memory Redis stand-in.
        placement (EnginePlacement): The placement being shown, shared by both threads as it is in the engine.
        body (dict): The caller's order body.
        worker_lines (list): What the worker thread printed, kept so it is printed in order.
    """

    def __init__(self):
        """Sets the configuration, fills Redis and builds the placement.

        Returns:
            None: This method returns nothing.
        """
        api_configuration['order_broker_selector'] = 'fixed_priority'
        api_configuration['order_broker_priority'] = [
            'zerodha',
            'dhan',
        ]
        api_configuration['order_excluded_brokers'] = []
        api_configuration['order_warm_brokers'] = []
        self.cache = FakeRedis()
        self.fill_redis()
        self.placement = EnginePlacement(self.cache, logging.getLogger('example'))
        self.body = {
            'instrument_id': INFOSYS_ID,
            'transaction_type': 'SELL',
            'product': 'MIS',
            'order_type': 'LIMIT',
            'price': 1422.0,
            'quantity': 25,
        }
        self.worker_lines = []

    def fill_redis(self):
        """Writes the mapping marker, Infosys's catalogue entry and the brokers' logins and settings.

        Returns:
            None: This method returns nothing.
        """
        prefix = f'unified:catalogue:{MAPPING_DATE}:'
        self.cache.strings['unified:catalogue:current_date'] = MAPPING_DATE
        self.cache.strings['unified:catalogue:warm_identifier'] = 'warm-0930-a'
        self.cache.hashes[prefix + 'identity'] = {
            INFOSYS_ID: json.dumps({
                'instrument_id': INFOSYS_ID,
                'exchange': 'nse',
                'segment': 'nse_equities',
                'shape': 'security',
                'symbol': 'INFY',
                'mapping_date': MAPPING_DATE,
            }),
        }
        self.cache.hashes[prefix + 'order_handles'] = {
            INFOSYS_ID: json.dumps({
                'zerodha': {
                    'broker_token': '408065',
                    'order_symbol': 'INFY',
                    'lot_size': 1.0,
                    'tick_size': 0.05,
                },
                'dhan': {
                    'broker_token': '1594',
                    'order_symbol': 'INFY',
                    'lot_size': 1.0,
                    'tick_size': 0.05,
                },
            }),
        }
        self.cache.hashes['last_login'] = {
            'dhan': json.dumps({
                'broker_name': 'dhan',
                'access_token': 'dhan-access-token',
            }),
            'kotak': json.dumps({
                'broker_name': 'kotak',
                'access_token': 'kotak-access-token',
                'sid': 'kotak-sid',
                'base_url': 'e21.kotaksecurities.com/',
            }),
        }
        self.cache.hashes['settings'] = {
            'dhan': json.dumps({
                'client_id': '1100000001',
            }),
            'zerodha': json.dumps({
                'api_key': 'kite-api-key',
            }),
        }

    def intent(self, body):
        """Wraps a body as the intent document intake reads.

        Args:
            body (dict): The caller's order body.

        Returns:
            dict: The intent.
        """
        return {
            'intent_id': '3f2a1b0c9d8e4f7a6b5c4d3e2f1a0b9c',
            'instrument_id': INFOSYS_ID,
            'body': body,
        }

    def run_worker(self, broker_name, skipped):
        """Runs on a worker thread: takes the assignment, prepares one leg and clears the assignment.

        Args:
            broker_name (str | None): The broker intake chose.
            skipped (list): The brokers intake passed over.

        Returns:
            None: This method returns nothing.
        """
        self.placement.use_assignment(broker_name, skipped)
        self.worker_lines.append(f'worker holds assignment: {self.placement.assignment.broker_name}')
        prepared = self.placement.prepare(PlaceOrderRequest(self.body), INFOSYS_ID)
        self.worker_lines.append(f'worker leg goes to {prepared.broker_name}, skipped {prepared.skipped}')
        self.placement.clear_assignment()
        self.worker_lines.append(f'worker assignment after clearing: {self.placement.assignment.broker_name}')

    def run(self):
        """Assigns at intake, prepares on both threads and shows the cases intake treats differently.

        Returns:
            None: This method returns nothing.
        """
        broker_name, skipped = self.placement.assign_broker(self.intent(self.body))
        print(f'intake chose {broker_name}, passing over {skipped}')

        worker = threading.Thread(
            target=self.run_worker,
            args=(
                broker_name,
                skipped,
            ),
        )
        worker.start()
        worker.join()
        for line in self.worker_lines:
            print(line)

        print(f'main thread holds assignment: {self.placement.assignment.broker_name}')

        closing_body = dict(self.body)
        closing_body['broker'] = 'kotak'
        print(f'a body that names its broker: {self.placement.assign_broker(self.intent(closing_body))}')

        broken_body = dict(self.body)
        broken_body['quantity'] = -5
        print(f'a body that does not validate: {self.placement.assign_broker(self.intent(broken_body))}')

        self.placement.use_assignment('kotak', [])
        prepared = self.placement.prepare(PlaceOrderRequest(self.body), INFOSYS_ID)
        print(f'assigned kotak, which has no mapping for Infosys, so the leg goes to {prepared.broker_name}')
        self.placement.clear_assignment()


if __name__ == '__main__':
    IntakeAssignsTheBrokerExample().run()
