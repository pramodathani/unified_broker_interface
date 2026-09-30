"""Shows the milestone tables a stepped stop refuses, and how it treats a trigger the caller moves before and after the trail takes over.

`SteppedStop.read_rules` checks the table before anything is sent. This program prints the HTTP 400 refusal for four bad tables: gains that do not increase, a stop placed at or past the gain that moves it, a trailing rule that is not the last, and a rule with both `stop_at_gain` and `trail_points`. `required_price` refuses an order without `entry_price`, and `run` refuses `trail_points` given outside the rules.

It then runs a stepped stop protecting a short of 20 INFY entered at 1,500, and plays the part of a caller who moves the stop's trigger through `PUT /api/orders/modify`. Before the trail has taken over, `on_leg_modified` leaves everything alone, because the milestones are measured from the entry, not from the stop. After a trailing rule has taken over, it moves the watermark so the trail carries on from the caller's trigger.

The placement is a stand-in that chooses Zerodha and accepts every order and change; the event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine. The caller's changes are recorded as the `leg_update` event `apply_outside_modification` writes.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/stepped_stop/SteppedStop/example_2_rule_checks_and_caller_change.py
"""

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
from unified_broker_interface.utilities.order_engine.stepped_stop import (
    SteppedStop,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000002'


class StandInAnswer:
    """What the stand-in broker answers a change or a cancel with.

    Attributes:
        outcome (str): `accepted` or `rejected`.
        status_message (str | None): Why, when it was not accepted.
        response_body (dict): The broker's body.
    """

    def __init__(self, outcome, status_message=None):
        """Builds the answer.

        Args:
            outcome (str): `accepted` or `rejected`.
            status_message (str | None): Why, when it was not accepted.

        Returns:
            None: This method returns nothing.
        """
        self.outcome = outcome
        self.status_message = status_message
        self.response_body = {
            'status': 'success' if outcome == 'accepted' else 'error',
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
        """The request as the event log and a dry run show it.

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
        self.identifier_sent = 'SYMBOL'
        self.skipped = []
        self.broker_quantity = broker_request.body['quantity']


class StandInPlacement:
    """Stands in for the engine's placement: serves fixed quotes and positions, chooses Zerodha, and accepts every order, change and cancel.

    Attributes:
        quotes (dict): The live quote for each instrument id.
        positions (dict | None): The unified positions document.
        identities (dict): The identity for each instrument id, where it is not an NSE equity.
        tick_size (str): The tick size every broker agrees on.
        lot_sizes (dict): The lot size for each instrument id, where it is not 1.
        attributes (dict): Every broker's extra fields, such as a freeze quantity.
        refuse_places (bool): Whether the broker refuses new orders.
        cache (object | None): The Redis stand-in an order type reads directly, or None when it reads nothing.
        messages (list): A line for every request the broker received, in order.
        next_number (int): The number the next broker order id is made from.
    """

    def __init__(self, quotes=None, positions=None, tick_size='0.05'):
        """Builds the stand-in.

        Args:
            quotes (dict | None): The live quote for each instrument id.
            positions (dict | None): The unified positions document.
            tick_size (str): The tick size every broker agrees on.

        Returns:
            None: This method returns nothing.
        """
        self.quotes = quotes or {}
        self.positions = positions
        self.identities = {}
        self.tick_size = tick_size
        self.lot_sizes = {}
        self.attributes = {}
        self.refuse_places = False
        self.cache = None
        self.messages = []
        self.next_number = 1

    def market_context(self, instrument_id, needs_quote, needs_positions):
        """Answers with the instrument, its quote and the positions.

        Args:
            instrument_id (str): The instrument.
            needs_quote (bool): Whether the quote is wanted.
            needs_positions (bool): Whether the positions are wanted.

        Returns:
            tuple: The instrument (Instrument), the quote (dict | None) and the positions (dict | None).
        """
        identity = self.identities.get(instrument_id)
        if identity is None:
            identity = {
                'segment': 'nse_equities',
            }
        instrument = Instrument(
            instrument_id,
            identity,
            {
                'zerodha': {
                    'order_symbol': 'SYMBOL',
                    'lot_size': self.lot_sizes.get(instrument_id, 1),
                    'tick_size': self.tick_size,
                },
            },
        )
        quote = None
        if needs_quote:
            quote = self.quotes.get(instrument_id)
        positions = None
        if needs_positions:
            positions = self.positions
        return instrument, quote, positions

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

    def broker_attributes(self, instrument_id):
        """Every broker's extra fields for the instrument.

        Args:
            instrument_id (str): The instrument, unused.

        Returns:
            dict: Broker names to their attributes.
        """
        del instrument_id
        return self.attributes

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
        """Sends the order to the stand-in broker, which accepts it unless told to refuse.

        Args:
            prepared_placement (StandInPreparedPlacement): The prepared order.
            started_at (float): When the engine took the intent, unused.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        del started_at
        body = prepared_placement.broker_request.body
        described = f"place {body['transaction_type']} {body['quantity']} {body['order_type']}"
        if body['price'] is not None:
            described = f"{described} at {body['price']}"
        if body['trigger_price'] is not None:
            described = f"{described} trigger {body['trigger_price']}"
        if self.refuse_places:
            self.messages.append(f'{described} -> refused')
            return {
                'broker': prepared_placement.broker_name,
                'outcome': 'rejected',
                'order_id': None,
                'status_message': 'the stand-in broker refused the order',
                'broker_response': {
                    'status': 'error',
                },
            }, 400
        order_id = f'2609300000{self.next_number:02d}'
        self.next_number = self.next_number + 1
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
        return StandInAnswer('accepted')

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
        return StandInAnswer('accepted')


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


class RuleChecksAndCallerChangeExample:
    """Prints refusals, then moves a stepped stop's trigger as a caller would.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
    """

    def __init__(self):
        """Builds the stand-in placement.

        Returns:
            None: This method returns nothing.
        """
        self.placement = StandInPlacement()

    def runner(self, synthetic):
        """A stepped stop over a short of 20 INFY, with its intent.

        Args:
            synthetic (dict): The order type's parameters.

        Returns:
            tuple: The runner (SteppedStop) and its intent (dict).
        """
        intent = {
            'intent_id': 'intent-1',
            'instrument_id': INSTRUMENT_ID,
            'body': {
                'instrument_id': INSTRUMENT_ID,
                'transaction_type': 'SELL',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'price': 1500,
                'quantity': 20,
                'synthetic': synthetic,
            },
        }
        runner = SteppedStop.started(
            intent,
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )
        return runner, intent

    def settings(self, rules):
        """A stepped stop's settings with the given rules.

        Args:
            rules (list): The milestone table.

        Returns:
            dict: The settings.
        """
        return {
            'type': 'stepped_stop',
            'entry_price': 1500,
            'stop_price': 1520,
            'stop_limit_offset': 2,
            'rules': rules,
        }

    def refusal(self, heading, rules):
        """Prints the refusal for a bad milestone table.

        Args:
            heading (str): What is wrong with it.
            rules (list): The table.

        Returns:
            None: This method returns nothing.
        """
        runner, _ = self.runner(self.settings(rules))
        try:
            runner.read_rules()
        except RefusedRequestError as refusal:
            print(f"{heading}: HTTP {refusal.status}, {refusal.body['error']}")

    def move_trigger(self, runner, trigger):
        """Records a caller's move of the stop's trigger and lets the stepped stop respond.

        Args:
            runner (SteppedStop): The stepped stop.
            trigger (float): The new trigger.

        Returns:
            None: This method returns nothing.
        """
        stop = runner.parent.legs[0]
        before = {
            'quantity': stop.quantity,
            'price': stop.price,
            'trigger_price': stop.trigger_price,
        }
        runner.record({
            'event': 'leg_update',
            'parent_state': runner.parent.state,
            'leg_id': stop.leg_id,
            'leg_role': stop.role,
            'trigger_price': trigger,
            'price': trigger + 2,
        })
        runner.on_leg_modified(stop, before)

    def run(self):
        """Prints the refusals and moves the trigger twice.

        Returns:
            None: This method returns nothing.
        """
        self.refusal(
            'Gains not increasing',
            [
                {
                    'gain': 20,
                    'stop_at_gain': 0,
                },
                {
                    'gain': 10,
                    'stop_at_gain': 5,
                },
            ],
        )
        self.refusal(
            'Stop past its gain',
            [
                {
                    'gain': 20,
                    'stop_at_gain': 25,
                },
            ],
        )
        self.refusal(
            'Trailing rule not last',
            [
                {
                    'gain': 20,
                    'trail_points': 10,
                },
                {
                    'gain': 40,
                    'stop_at_gain': 15,
                },
            ],
        )
        self.refusal(
            'Both kinds in one rule',
            [
                {
                    'gain': 20,
                    'stop_at_gain': 0,
                    'trail_points': 10,
                },
            ],
        )
        no_entry, _ = self.runner({
            'type': 'stepped_stop',
            'stop_price': 1520,
        })
        try:
            no_entry.required_price('entry_price')
        except RefusedRequestError as refusal:
            print(f"No entry_price: HTTP {refusal.status}, {refusal.body['error']}")
        trailing = self.settings([
            {
                'gain': 20,
                'trail_points': 10,
            },
        ])
        trailing['trail_points'] = 10
        stray, stray_intent = self.runner(trailing)
        try:
            stray.run(stray_intent, time.perf_counter())
        except RefusedRequestError as refusal:
            print(f"trail_points outside the rules: HTTP {refusal.status}, {refusal.body['error']}")

        runner, intent = self.runner(self.settings([
            {
                'gain': 20,
                'trail_points': 10,
            },
        ]))
        runner.run(intent, time.perf_counter())
        self.move_trigger(runner, 1525.0)
        print(f"Caller moved the trigger to 1525 before the trail: watermark {runner.parent.parameters.get('watermark')}")
        runner.on_price_tick(
            {
                INSTRUMENT_ID: {
                    'last_price': 1478.00,
                },
            },
            1790000000.0,
        )
        print(f"At 1478 the trail takes over: trail_points {runner.parent.parameters['trail_points']}, watermark {runner.parent.parameters['watermark']}, trigger {runner.parent.legs[0].trigger_price}")
        self.move_trigger(runner, 1492.0)
        print(f"Caller moved the trigger to 1492 during the trail: watermark {runner.parent.parameters['watermark']}")
        print('Sent to the broker:')
        for message in self.placement.messages:
            print(f'  {message}')


if __name__ == '__main__':
    RuleChecksAndCallerChangeExample().run()
