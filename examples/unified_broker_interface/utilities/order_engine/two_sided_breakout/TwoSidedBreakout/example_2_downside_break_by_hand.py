"""Calls a two-sided breakout's steps by hand for a downside break, and shows the ranges it refuses.

A `TwoSidedBreakout` is built from steps that this program calls directly on INFY around a range of 1,480 to 1,520, for 30 shares, with exits written for a short: a stop at 1,500 (limit 1,502) and a target at 1,450.

- `entry_orders` builds the two stop-limit entries, a buy above the range and a sell below;
- `answer` turns the brokers' answers into the one answer the caller gets, listing each side;
- `cancel_other_side` cancels the buy entry once the sell side has filled;
- `arm_exits` places the stop and target on the side that actually filled, as buys, because the position is short;
- `on_entry_update` with the sell side cancelled by the broker without a fill does nothing to the other side.

Last, `entry_orders` refuses two ranges with HTTP 400: one missing its limits, and one whose sell trigger is not below its buy trigger. The placement is a stand-in that chooses Zerodha and accepts every order and cancel; the event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine. Fills are recorded as the `leg_update` events the engine's order update follower writes.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/two_sided_breakout/TwoSidedBreakout/example_2_downside_break_by_hand.py
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
from unified_broker_interface.utilities.order_engine.two_sided_breakout import (
    TwoSidedBreakout,
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


class DownsideBreakByHandExample:
    """Drives a two-sided breakout's steps by hand, then prints refusals.

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
        """A two-sided breakout on 30 INFY, with its intent.

        Args:
            synthetic (dict): The order type's parameters.

        Returns:
            tuple: The runner (TwoSidedBreakout) and its intent (dict).
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
                'quantity': 30,
                'synthetic': synthetic,
            },
        }
        runner = TwoSidedBreakout.started(
            intent,
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )
        return runner, intent

    def record(self, runner, leg, changes):
        """Records an order update on a leg, without letting the breakout react.

        Args:
            runner (TwoSidedBreakout): The breakout.
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

    def run(self):
        """Drives the steps and prints the refusals.

        Returns:
            None: This method returns nothing.
        """
        runner, intent = self.runner({
            'type': 'two_sided_breakout',
            'buy_trigger': 1520,
            'buy_limit': 1522,
            'sell_trigger': 1480,
            'sell_limit': 1478,
            'stop_price': 1500,
            'stop_limit_price': 1502,
            'target_price': 1450,
        })
        order = runner.read_order(runner.parent.body)
        for role, entry in runner.entry_orders(order):
            print(f'entry_orders: {role} {entry.transaction_type} {entry.quantity} {entry.order_type} at {entry.price} trigger {entry.trigger_price}')
        runner.record_received()
        answers = []
        for role, entry in runner.entry_orders(order):
            body, status, _ = runner.place_leg(role, entry, time.perf_counter())
            answers.append((
                role,
                body,
                status,
            ))
        body, status = runner.answer(answers, 'zerodha')
        print(f"answer: HTTP {status}, outcome {body['outcome']}, sides {body['sides']}")

        buy, sell = runner.parent.legs
        self.record(
            runner,
            sell,
            {
                'leg_state': 'filled',
                'filled_quantity': 30,
            },
        )
        runner.cancel_other_side(sell)
        runner.arm_exits(sell, 30)
        print(f'After the sell side filled: parent {runner.parent.state}')
        for leg in runner.exit_legs():
            print(f'  {leg.role:<6} {leg.transaction_type} {leg.quantity} {leg.order_type} at {leg.price} trigger {leg.trigger_price}')
        print('Sent to the broker, in order:')
        for message in self.placement.messages:
            print(f'  {message}')

        quiet, quiet_intent = self.runner({
            'type': 'two_sided_breakout',
            'buy_trigger': 1520,
            'buy_limit': 1522,
            'sell_trigger': 1480,
            'sell_limit': 1478,
            'stop_price': 1500,
            'stop_limit_price': 1502,
        })
        quiet.run(quiet_intent, time.perf_counter())
        sent_before = len(self.placement.messages)
        cancelled = quiet.parent.legs[1]
        changes = {
            'leg_state': 'cancelled',
        }
        self.record(quiet, cancelled, changes)
        quiet.on_entry_update(cancelled, changes)
        print(f'on_entry_update for a side cancelled unfilled: orders sent {len(self.placement.messages) - sent_before}, parent {quiet.parent.state}')

        mistakes = [
            (
                'Missing the limits',
                {
                    'type': 'two_sided_breakout',
                    'buy_trigger': 1520,
                    'sell_trigger': 1480,
                },
            ),
            (
                'A range upside down',
                {
                    'type': 'two_sided_breakout',
                    'buy_trigger': 1480,
                    'buy_limit': 1482,
                    'sell_trigger': 1520,
                    'sell_limit': 1518,
                },
            ),
        ]
        for heading, synthetic in mistakes:
            careless, _ = self.runner(synthetic)
            try:
                careless.entry_orders(careless.read_order(careless.parent.body))
            except RefusedRequestError as refusal:
                print(f"{heading}: HTTP {refusal.status}, {refusal.body['error']}")


if __name__ == '__main__':
    DownsideBreakByHandExample().run()
