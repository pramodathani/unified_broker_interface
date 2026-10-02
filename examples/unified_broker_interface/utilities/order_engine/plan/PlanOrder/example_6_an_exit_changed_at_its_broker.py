"""Changes a bracket's exits at their broker after the entry fills, and shows the plan refusing a raise and following a cut.

Once a bracket's entry fills, its stop and target rest at the broker, and a caller changes them with `PUT /api/orders/modify` naming the broker and order id. Two methods of `PlanOrder` take part in that. `outside_change_problem` is asked before anything is sent: an order that closes a position can only be reduced, so it refuses raising the stop from 10 to 15 but lets the target be cut to 6. `on_leg_modified` is called once the broker has accepted the change: the target's new quantity comes off the quantity both exits share, because a bracket's exits sit under an Either join that reduces, so the plan cuts the stop to 6 as well and both exits keep closing exactly what is held.

The program records the cut the way the modify route records it after the broker accepts, which leaves the target holding its new quantity, and then hands the change to `on_leg_modified`.

The engine's placement is a small stand-in that always chooses Zerodha and accepts every order and change, and the event log is the `RecordingEventLog` stand-in from the offline suites, so nothing leaves the machine. RELIANCE's tick size is 0.10.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/plan/PlanOrder/example_6_an_exit_changed_at_its_broker.py
"""

import logging
import time

from test_runs.engine_stand_ins import (
    RecordingEventLog,
)
from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.order_engine.plan import (
    PlanOrder,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'


class StandInAnswer:
    """What the stand-in broker answers a change or a cancel with.

    Attributes:
        outcome (str): Always `accepted`.
        status_message (str | None): Always None.
        response_body (dict): The broker's body.
    """

    def __init__(self):
        """Builds an accepting answer.

        Returns:
            None: This method returns nothing.
        """
        self.outcome = 'accepted'
        self.status_message = None
        self.response_body = {
            'status': 'success',
        }


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
    """Stands in for the engine's placement: chooses Zerodha and accepts every order, change and cancel.

    Attributes:
        messages (list): A line for every request the broker received, in order.
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

    def modify_leg(
        self,
        broker_name,
        broker_order_id,
        quantity=None,
        price=None,
        trigger_price=None,
    ):
        """Changes an order at the stand-in broker, which accepts.

        Args:
            broker_name (str): The broker, unused.
            broker_order_id (str): The order.
            quantity (int | None): The new quantity.
            price (decimal.Decimal | None): The new price.
            trigger_price (decimal.Decimal | None): The new trigger price.

        Returns:
            StandInAnswer: The answer.
        """
        del broker_name
        described = f'modify {broker_order_id}'
        if quantity is not None:
            described = f'{described} quantity {quantity}'
        if price is not None:
            described = f'{described} price {price}'
        if trigger_price is not None:
            described = f'{described} trigger {trigger_price}'
        self.messages.append(described)
        return StandInAnswer()

    def cancel(self, broker_name, broker_order_id):
        """Cancels an order at the stand-in broker, which accepts.

        Args:
            broker_name (str): The broker, unused.
            broker_order_id (str): The order.

        Returns:
            StandInAnswer: The answer.
        """
        del broker_name
        self.messages.append(f'cancel {broker_order_id}')
        return StandInAnswer()


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




class AnExitChangedAtItsBrokerExample:
    """Fills a bracket's entry and changes its exits as a caller would through the modify route.

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

    def leg_with_role(self, role):
        """The broker order a part placed.

        Args:
            role (str): The part's path.

        Returns:
            OrderLeg: The leg.

        Raises:
            ValueError: When no leg has that role.
        """
        for leg in self.runner.parent.legs:
            if leg.role == role:
                return leg
        raise ValueError(f'No leg has the role: {role=}')

    def cut_target(self, target, quantity):
        """Sends a cut of the target to the broker, records it as the modify route does once the broker accepts, and hands it to the plan.

        Args:
            target (OrderLeg): The target leg.
            quantity (int): Its new quantity.

        Returns:
            None: This method returns nothing.
        """
        before = {
            'quantity': target.quantity,
            'price': target.price,
            'trigger_price': target.trigger_price,
        }
        self.placement.modify_leg(target.broker, target.broker_order_id, quantity=quantity)
        self.runner.record({
            'event': 'leg_update',
            'parent_state': self.runner.parent.state,
            'leg_id': target.leg_id,
            'leg_role': target.role,
            'broker': target.broker,
            'broker_order_id': target.broker_order_id,
            'outcome': 'accepted',
            'status_message': 'changed through PUT /api/orders/modify; accepted',
            'quantity': quantity,
            'detail': {
                'changed_by': 'caller',
            },
        })
        print(f'The target after the broker accepted the cut: {target.quantity}')
        self.runner.on_leg_modified(target, before)

    def run(self):
        """Places the bracket, fills its entry, and changes its exits.

        Returns:
            None: This method returns nothing.
        """
        body, status = self.runner.run(self.intent, time.perf_counter())
        print(f"Answer: HTTP {status}, {body['outcome']}")
        self.fill_entry()
        stop = self.leg_with_role('root.each_fill.children.0')
        target = self.leg_with_role('root.each_fill.children.1')
        print(f'Exits working: stop {stop.quantity} trigger {stop.trigger_price}, target {target.quantity} at {target.price}')
        print(f'outside_change_problem raising the stop to 15: {self.runner.outside_change_problem(stop, 15)}')
        print(f'outside_change_problem cutting the target to 6: {self.runner.outside_change_problem(target, 6)}')
        print(f'outside_change_problem moving only a price: {self.runner.outside_change_problem(stop, None)}')
        self.cut_target(target, 6)
        print(f'Exits after on_leg_modified: stop {stop.quantity}, target {target.quantity}')
        print(f"The exits' shared part: {self.runner.part_record('root.each_fill')}")
        print('Sent to the broker, in order:')
        for message in self.placement.messages:
            print(f'  {message}')
        print(f'Parent: {self.runner.parent.state}')


if __name__ == '__main__':
    AnExitChangedAtItsBrokerExample().run()
