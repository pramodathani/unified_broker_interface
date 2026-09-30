"""Calls a bracket's arming steps one at a time, and shows the bracket it refuses before sending anything.

`Bracket.on_leg_update` is a dispatcher: an update to the entry goes to `on_entry_update`, and one to an exit goes to `on_exit_update`. Underneath are the steps this program calls directly, on a short-sale bracket that sells 50 INFY at 1,500 with a stop at 1,515 (limit 1,518) and a target at 1,470:

- `exit_legs` lists the stop and target, and is empty until the entry has filled;
- `arm_exits` places both exits for what has filled, as buys because the entry is a sell;
- `grow_exits` changes the exits' quantity to follow a larger fill;
- `on_entry_update` does whichever of the two is needed;
- `cancel_working_entry` stops the rest of the entry once an exit has started filling;
- `on_exit_update` runs the one-cancels-other rules after an exit fills, which here cancels the target because the stop closed the whole position.

Last, it runs a bracket whose stop has no `stop_limit_price`. That is refused with HTTP 400 before the entry is sent, because a stop-limit whose limit sits at its trigger does not fill when the price runs through it, and refusing after the entry had filled would leave an unprotected position.

The placement is a stand-in that chooses Zerodha and accepts every order, change and cancel; the event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine. Fills are recorded as `leg_update` events through the runner, as the engine's order update follower records them.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/bracket/Bracket/example_2_arming_step_by_step.py
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
from unified_broker_interface.utilities.order_engine.bracket import (
    Bracket,
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


class ArmingStepByStepExample:
    """Drives a short-sale bracket through its steps, then shows a refusal.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
    """

    def __init__(self):
        """Builds the stand-in placement.

        Returns:
            None: This method returns nothing.
        """
        self.placement = StandInPlacement()

    def intent(self, synthetic):
        """An intent to sell 50 INFY at 1,500 with the given exits.

        Args:
            synthetic (dict): The order type's parameters.

        Returns:
            dict: The intent.
        """
        return {
            'intent_id': 'intent-1',
            'instrument_id': INSTRUMENT_ID,
            'body': {
                'instrument_id': INSTRUMENT_ID,
                'transaction_type': 'SELL',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'price': 1500,
                'quantity': 50,
                'synthetic': synthetic,
            },
        }

    def record_fill(self, runner, leg, filled_quantity, state):
        """Records a fill on a leg without letting the bracket react.

        Args:
            runner (Bracket): The bracket.
            leg (OrderLeg): The leg.
            filled_quantity (int): How much has filled in all.
            state (str): The leg's new state.

        Returns:
            dict: The changes, as the order update follower would hand them over.
        """
        changes = {
            'leg_state': state,
            'filled_quantity': filled_quantity,
        }
        event = {
            'event': 'leg_update',
            'parent_state': runner.parent.state,
            'leg_id': leg.leg_id,
            'leg_role': leg.role,
        }
        event.update(changes)
        runner.record(event)
        return changes

    def show_exits(self, runner):
        """Prints the exit legs.

        Args:
            runner (Bracket): The bracket.

        Returns:
            None: This method returns nothing.
        """
        exits = runner.exit_legs()
        if not exits:
            print('  no exits yet')
        for leg in exits:
            print(f'  {leg.role:<6} {leg.transaction_type} {leg.quantity} {leg.order_type} at {leg.price} trigger {leg.trigger_price}, {leg.state}')

    def run(self):
        """Drives the bracket step by step and prints the refusal.

        Returns:
            None: This method returns nothing.
        """
        synthetic = {
            'type': 'bracket',
            'stop_price': 1515,
            'stop_limit_price': 1518,
            'target_price': 1470,
        }
        intent = self.intent(synthetic)
        runner = Bracket.started(
            intent,
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )
        runner.run(intent, time.perf_counter())
        entry = runner.parent.legs[0]
        print('Before any fill:')
        self.show_exits(runner)

        self.record_fill(runner, entry, 20, 'partially_filled')
        runner.arm_exits(entry, 20)
        print(f'arm_exits for 20, parent {runner.parent.state}:')
        self.show_exits(runner)

        self.record_fill(runner, entry, 35, 'partially_filled')
        runner.grow_exits(runner.exit_legs(), 35)
        print('grow_exits to 35:')
        self.show_exits(runner)

        changes = self.record_fill(runner, entry, 45, 'partially_filled')
        runner.on_entry_update(entry, changes)
        print('on_entry_update after 45 filled:')
        self.show_exits(runner)

        stop = runner.exit_legs()[0]
        changes = self.record_fill(runner, stop, 45, 'filled')
        runner.cancel_working_entry(stop)
        self.record_fill(runner, entry, 45, 'cancelled')
        runner.on_exit_update(stop, changes)
        print('The stop filled 45; cancel_working_entry, the entry cancel confirmed, then on_exit_update:')
        self.show_exits(runner)
        print(f'Parent: {runner.parent.state}')
        print('Sent to the broker:')
        for message in self.placement.messages:
            print(f'  {message}')

        careless = self.intent({
            'type': 'bracket',
            'stop_price': 1515,
            'target_price': 1470,
        })
        refused = Bracket.started(
            careless,
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )
        sent_before = len(self.placement.messages)
        try:
            refused.run(careless, time.perf_counter())
        except RefusedRequestError as refusal:
            print(f"No stop_limit_price: HTTP {refusal.status}, {refusal.body['error']}")
        print(f'Orders sent for it: {len(self.placement.messages) - sent_before}')


if __name__ == '__main__':
    ArmingStepByStepExample().run()
