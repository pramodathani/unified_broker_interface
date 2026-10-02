"""Places a bracket plan whose entry rests, moves its stop before the entry fills, and shows the stop sent at the new prices.

A bracket plan sends its entry first and keeps its stop and target unsent until the entry fills, because they are sized by what it fills. `PlanOrder.modify_part`, which `PUT /api/orders/modify` reaches with the parent's id and a `part`, changes such an unsent part. This program buys ten RELIANCE at 1,000 with a stop at 990 (limit 988) and a target at 1,010, and while the entry rests:

1. A dry run moves the stop part, `root.each_fill.children.0`, to trigger 985 and limit 983, and answers without changing anything.
2. The same change is made for real, and kept in the part's record.
3. A new quantity for the stop is refused with HTTP 409, because the stop is sized by the entry's fills.
4. A change to `root.first`, the entry, is refused with HTTP 409 naming its broker order, since an order already sent is changed at its broker.
5. A trigger price for the target is refused with HTTP 400, because the target is not a stop.
6. A part the plan does not have is refused with HTTP 404.

Then the entry fills, and the stop goes out at trigger 985 and limit 983 instead of 990 and 988.

The engine's placement is a small stand-in that always chooses Zerodha and accepts every order, and the event log is the `RecordingEventLog` stand-in from the offline suites, so nothing leaves the machine. RELIANCE's tick size is 0.10.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/plan/PlanOrder/example_5_a_bracket_stop_moved_before_it_is_sent.py
"""

import decimal
import logging
import time

from test_runs.engine_stand_ins import (
    RecordingEventLog,
)
from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.plan import (
    PlanOrder,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'

STOP_PART = 'root.each_fill.children.0'


class StandInBrokerRequest:
    """A request built for a broker, reduced to what the engine reads from it.

    Attributes:
        tag (str | None): The tag the request carries.
        body (dict): The request's body.
    """

    def __init__(self, tag, body):
        """Builds the request.

        Args:
            tag (str | None): The tag the request carries.
            body (dict): The request's body.

        Returns:
            None: This method returns nothing.
        """
        self.tag = tag
        self.body = body

    def shown(self):
        """The request as the event log keeps it.

        Returns:
            dict: The method, URL and body.
        """
        return {
            'method': 'POST',
            'url': 'https://broker.example/orders',
            'json': self.body,
        }


class StandInPreparedPlacement:
    """An order given a broker and a request, but not yet sent.

    Attributes:
        instrument_id (str): The instrument the order is for.
        broker_name (str): The chosen broker.
        broker_request (StandInBrokerRequest): The request built for it.
        identifier_sent (str): The symbol the request names the instrument by.
        skipped (list): The brokers passed over, which is always none here.
        broker_quantity (int): The quantity the request carries, in the broker's own terms.
    """

    def __init__(self, instrument_id, broker_name, broker_request):
        """Builds the prepared placement.

        Args:
            instrument_id (str): The instrument the order is for.
            broker_name (str): The chosen broker.
            broker_request (StandInBrokerRequest): The request built for it.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = instrument_id
        self.broker_name = broker_name
        self.broker_request = broker_request
        self.identifier_sent = 'RELIANCE'
        self.skipped = []
        self.broker_quantity = broker_request.body['quantity']


class StandInPlacement:
    """Stands in for the engine's placement: chooses Zerodha and accepts every order.

    Attributes:
        messages (list): A line for every order the broker received, in order.
        next_number (int): The number the next broker order id is made from.
    """

    def __init__(self):
        """Builds the stand-in with nothing sent.

        Returns:
            None: This method returns nothing.
        """
        self.messages = []
        self.next_number = 1

    def market_context(self, instrument_id, needs_quote, needs_positions):
        """Answers with RELIANCE on the NSE, whose tick size every broker agrees is 0.10, no quote and no open positions.

        Args:
            instrument_id (str): The instrument.
            needs_quote (bool): Unused, since no quote is served.
            needs_positions (bool): Unused, since the positions are always empty.

        Returns:
            tuple: The instrument (Instrument), no quote and the positions (dict).
        """
        del needs_quote, needs_positions
        instrument = Instrument(
            instrument_id,
            {
                'segment': 'nse_equities',
            },
            {
                'zerodha': {
                    'order_symbol': 'RELIANCE',
                    'lot_size': 1,
                    'tick_size': '0.10',
                },
            },
        )
        return instrument, None, {
            'net': [],
        }

    def broker_quantity(self, broker_name, instrument_id, units):
        """Converts units into the broker's terms, which for an equity are the units themselves.

        Args:
            broker_name (str): The broker, unused.
            instrument_id (str): The instrument, unused.
            units (int): The quantity in units.

        Returns:
            int: The same quantity.
        """
        del broker_name, instrument_id
        return units

    def prepare(self, order, instrument_id, broker_name=None):
        """Chooses a broker and builds the request, without sending it.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument_id (str): The instrument.
            broker_name (str | None): The broker the order must go to, or None for Zerodha.

        Returns:
            StandInPreparedPlacement: The prepared order.
        """
        body = {
            'transaction_type': order.transaction_type,
            'order_type': order.order_type,
            'quantity': order.quantity,
            'price': None if order.price is None else str(order.price),
            'trigger_price': None if order.trigger_price is None else str(order.trigger_price),
        }
        broker_request = StandInBrokerRequest(order.tag, body)
        return StandInPreparedPlacement(
            instrument_id,
            broker_name or 'zerodha',
            broker_request,
        )

    def dry_run_answer(self, prepared_placement, started_at):
        """Answers with the request that would have been sent.

        Args:
            prepared_placement (StandInPreparedPlacement): The prepared order.
            started_at (float): When the engine took the intent, unused.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        del started_at
        return {
            'broker': prepared_placement.broker_name,
            'dry_run': True,
            'request': prepared_placement.broker_request.shown(),
        }, 200

    def send(self, prepared_placement, started_at):
        """Sends the order to the stand-in broker, which accepts it.

        Args:
            prepared_placement (StandInPreparedPlacement): The prepared order.
            started_at (float): When the engine took the intent, unused.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        del started_at
        body = prepared_placement.broker_request.body
        order_id = f'2609300000{self.next_number:02d}'
        self.next_number = self.next_number + 1
        described = f"place {body['transaction_type']} {body['quantity']} {body['order_type']}"
        if body['price'] is not None:
            described = f"{described} at {body['price']}"
        if body['trigger_price'] is not None:
            described = f"{described} trigger {body['trigger_price']}"
        self.messages.append(f'{described} -> {order_id}')
        return {
            'broker': prepared_placement.broker_name,
            'outcome': 'accepted',
            'order_id': order_id,
            'status_message': None,
            'broker_response': {
                'status': 'success',
                'data': {
                    'order_id': order_id,
                },
            },
        }, 200


class StandInParentStore:
    """Stands in for the Redis copy of the parents, keeping nothing."""

    def save(self, parent):
        """Accepts a parent without keeping it.

        Args:
            parent (ParentOrder): The parent.

        Returns:
            None: This method returns nothing.
        """
        del parent


class ABracketStopMovedBeforeItIsSentExample:
    """Moves a bracket's unsent stop while its entry rests, and fills the entry.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
        event_log (RecordingEventLog): Where the events are kept.
        intent (dict): The intent the REST API would have written.
        runner (PlanOrder): The order type running the parent.
    """

    def __init__(self):
        """Builds the runner from an intent for ten RELIANCE at 1,000.00 with the `bracket` preset.

        Returns:
            None: This method returns nothing.
        """
        self.placement = StandInPlacement()
        self.event_log = RecordingEventLog()
        self.intent = {
            'intent_id': 'intent-1',
            'instrument_id': INSTRUMENT_ID,
            'body': {
                'instrument_id': INSTRUMENT_ID,
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'quantity': 10,
                'price': '1000.00',
                'synthetic': {
                    'type': 'plan',
                    'plan': {
                        'order': {
                            'presets': [
                                {
                                    'bracket': {
                                        'stop_price': 990,
                                        'stop_limit_price': 988,
                                        'target_price': 1010,
                                    },
                                },
                            ],
                        },
                    },
                },
            },
        }
        self.runner = PlanOrder.started(
            self.intent,
            self.placement,
            self.event_log,
            StandInParentStore(),
            logging.getLogger('example'),
        )

    def show(self, label, path, price, trigger_price, quantity, dry_run):
        """Asks for one change to a part and prints the answer or the refusal.

        Args:
            label (str): What is being asked.
            path (str): The part's path.
            price (decimal.Decimal | None): The new limit price, or None.
            trigger_price (decimal.Decimal | None): The new trigger price, or None.
            quantity (int | None): The new quantity, or None.
            dry_run (bool): Whether only to check it.

        Returns:
            None: This method returns nothing.
        """
        try:
            body, status = self.runner.modify_part(path, price, trigger_price, quantity, dry_run)
        except RefusedRequestError as error:
            print(f"{label}: HTTP {error.status}, {error.body['error']}")
            if error.body.get('orders'):
                print(f"  Its broker orders: {error.body['orders']}")
            return
        print(f"{label}: HTTP {status}, {body['quantity']} trigger {body['trigger_price']} at {body['price']}, {body['status_message']}")

    def fill_entry(self):
        """Records a fill of the whole entry, as the order update follower would, and hands it to the plan.

        Returns:
            None: This method returns nothing.
        """
        entry = self.runner.parent.legs[0]
        self.runner.record({
            'event': 'leg_update',
            'parent_state': self.runner.parent.state,
            'leg_id': entry.leg_id,
            'leg_role': entry.role,
            'leg_state': 'filled',
            'filled_quantity': 10,
            'average_price': 1000.0,
        })
        self.runner.on_leg_update(
            entry,
            {
                'leg_state': 'filled',
                'filled_quantity': 10,
            },
        )

    def run(self):
        """Places the bracket, changes its stop and other parts, fills the entry, and prints what was sent.

        Returns:
            None: This method returns nothing.
        """
        body, status = self.runner.run(self.intent, time.perf_counter())
        print(f"Answer: HTTP {status}, {body['outcome']}, entry {body['legs'][0]['path']} order id {body['legs'][0]['order_id']}")
        self.show('A dry run moving the stop to trigger 985, limit 983', STOP_PART, decimal.Decimal('983'), decimal.Decimal('985'), None, True)
        print(f"  The stop part's record after the dry run: {self.runner.part_record(STOP_PART)}")
        self.show('The stop moved to trigger 985, limit 983', STOP_PART, decimal.Decimal('983'), decimal.Decimal('985'), None, False)
        print(f"  The stop part's record now: {self.runner.part_record(STOP_PART)}")
        self.show('The stop cut to 5', STOP_PART, None, None, 5, False)
        self.show('The entry moved to 999', 'root.first', decimal.Decimal('999'), None, None, False)
        self.show('A trigger of 1,012 for the target', 'root.each_fill.children.1', None, decimal.Decimal('1012'), None, False)
        self.show('A part the plan does not have', 'root.nowhere', decimal.Decimal('999'), None, None, False)
        self.fill_entry()
        print('Sent to the broker, in order:')
        for message in self.placement.messages:
            print(f'  {message}')
        print(f'Parent: {self.runner.parent.state}')


if __name__ == '__main__':
    ABracketStopMovedBeforeItIsSentExample().run()
