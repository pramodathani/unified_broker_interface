"""Calls a scale-out's steps one at a time on a short, and shows the setting it refuses.

A `ScaleOut` is built from steps that this program calls directly, on a short sale of 100 TCS at 4,000 with a stop at 4,040 (limit 4,050), targets at 3,960, 3,920 and 3,880, and `breakeven_after` of 2:

- `target_prices` reads the targets, and `tranches` shares a quantity between them;
- `arm_exits` for only two units, fewer than the targets, places the stop and a single target at the last price rather than orders for nothing;
- `grow_exits` brings the stop up to a larger fill and leaves the target alone;
- `rebalance` after the target fills reduces only the stop, and `move_stop_to_breakeven` does nothing yet because one target has filled and two are wanted;
- `entry_leg`, `live_stop` and `filled_targets` find the legs and count the filled targets;
- `on_leg_modified` leaves the other exits alone after a caller changes one.

Last, a single target price is refused with HTTP 400, because a scale-out needs at least two. The placement is a stand-in that chooses Zerodha and accepts every order and change; the event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine. Fills are recorded as the `leg_update` events the engine's order update follower writes.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/scale_out/ScaleOut/example_2_scale_out_steps_by_hand.py
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
from unified_broker_interface.utilities.order_engine.scale_out import (
    ScaleOut,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000010'


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


class ScaleOutStepsByHandExample:
    """Calls a scale-out's steps by hand.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
    """

    def __init__(self):
        """Builds the stand-in placement.

        Returns:
            None: This method returns nothing.
        """
        self.placement = StandInPlacement()

    def runner(self, target_prices):
        """A scale-out on a short of 100 TCS, with its intent.

        Args:
            target_prices (list): The target prices.

        Returns:
            tuple: The runner (ScaleOut) and its intent (dict).
        """
        intent = {
            'intent_id': 'intent-1',
            'instrument_id': INSTRUMENT_ID,
            'body': {
                'instrument_id': INSTRUMENT_ID,
                'transaction_type': 'SELL',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'price': 4000,
                'quantity': 100,
                'synthetic': {
                    'type': 'scale_out',
                    'stop_price': 4040,
                    'stop_limit_price': 4050,
                    'target_prices': target_prices,
                    'breakeven_after': 2,
                },
            },
        }
        runner = ScaleOut.started(
            intent,
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )
        return runner, intent

    def record(self, runner, leg, changes):
        """Records an order update on a leg, without letting the scale-out react.

        Args:
            runner (ScaleOut): The scale-out.
            leg (OrderLeg): The leg.
            changes (dict): What the update changed.

        Returns:
            None: This method returns nothing.
        """
        event = {
            'event': 'leg_update',
            'parent_state': runner.parent.state,
            'leg_id': leg.leg_id,
            'leg_role': leg.role,
        }
        event.update(changes)
        runner.record(event)

    def show(self, runner, heading):
        """Prints the exit legs.

        Args:
            runner (ScaleOut): The scale-out.
            heading (str): What just happened.

        Returns:
            None: This method returns nothing.
        """
        print(f'{heading}:')
        for leg in runner.exit_legs():
            print(f'  {leg.role:<6} {leg.transaction_type} {leg.quantity} at {leg.price}, filled {leg.filled_quantity}')

    def run(self):
        """Calls the steps and prints the refusal.

        Returns:
            None: This method returns nothing.
        """
        runner, intent = self.runner([
            3960,
            3920,
            3880,
        ])
        print(f'target_prices: {runner.target_prices()}, tranches of 100: {runner.tranches(100, 3)}')
        runner.run(intent, time.perf_counter())
        entry = runner.entry_leg()
        self.record(
            runner,
            entry,
            {
                'leg_state': 'partially_filled',
                'filled_quantity': 2,
                'average_price': 4000.00,
            },
        )
        runner.arm_exits(entry, 2)
        self.show(runner, 'arm_exits for 2')
        self.record(
            runner,
            entry,
            {
                'leg_state': 'filled',
                'filled_quantity': 100,
            },
        )
        runner.grow_exits(runner.exit_legs(), 100)
        self.show(runner, 'grow_exits to 100')

        target = runner.exit_legs()[1]
        self.record(
            runner,
            target,
            {
                'leg_state': 'filled',
                'filled_quantity': 2,
            },
        )
        runner.rebalance(target)
        self.show(runner, 'rebalance after the target filled 2')
        runner.move_stop_to_breakeven()
        print(f'filled_targets {runner.filled_targets()}, stop at breakeven {runner.parent.parameters.get("stop_at_breakeven")}, live_stop at {runner.live_stop().price}')
        runner.on_leg_modified(runner.live_stop(), {})
        print('Sent to the broker:')
        for message in self.placement.messages:
            print(f'  {message}')

        single, _ = self.runner([
            3960,
        ])
        try:
            single.target_prices()
        except RefusedRequestError as refusal:
            print(f"One target: HTTP {refusal.status}, {refusal.body['error']}")


if __name__ == '__main__':
    ScaleOutStepsByHandExample().run()
