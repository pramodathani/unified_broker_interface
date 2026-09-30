"""Shows every way `SyntheticOrder` cancels: one leg, a whole parent at a caller's request, an order it did not place, or just stopping.

Every cancel is recorded as asked before it is sent and as answered after, so a crash in between leaves evidence. This program places legs through `place_leg` on plain `SyntheticOrder` runners and then cancels them against a stand-in broker that refuses to cancel one particular order:

1. `cancel_leg` cancels a leg and says whether the broker accepted; `cancel_leg_answered` says what the broker answered, which for the refused order is `rejected` with the reason.
2. `cancel_by_caller` cancels every resting leg of a parent. One cancel is refused, so the parent becomes `cancelling`, not `cancelled`: that leg may still be live. Once the broker reports both legs finished, `finish_cancelling` ends the parent as `cancelled`.
3. `stop_acting` ends a parent as `cancelled` without touching its legs, as flatten does before cancelling everything itself; a second call does nothing.
4. `cancel_outside_order` cancels an order that is not one of the parent's legs, recording it on the parent.
5. `abandon` closes a parent that was recorded and then refused before anything reached a broker, and leaves one that recorded nothing alone.

The placement is a stand-in that chooses Zerodha, accepts every order and every cancel but one; the event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine. The broker's reports are recorded as the `leg_update` events the engine's order update follower writes.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/base/SyntheticOrder/example_2_cancelling_legs_and_parents.py
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
from unified_broker_interface.utilities.order_engine.base import (
    SyntheticOrder,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'


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


class StubbornPlacement(StandInPlacement):
    """The stand-in placement, with a broker that refuses to cancel the orders it has been told to keep.

    Attributes:
        kept (set): The order ids whose cancels are refused.
    """

    def __init__(self):
        """Builds the stand-in with nothing kept.

        Returns:
            None: This method returns nothing.
        """
        super().__init__()
        self.kept = set()

    def cancel(self, broker_name, broker_order_id):
        """Cancels an order, refusing when it is one of the kept ones.

        Args:
            broker_name (str): The broker.
            broker_order_id (str): The order.

        Returns:
            StandInAnswer: The answer.

        Raises:
            RefusedRequestError: With HTTP 503 for a kept order.
        """
        if broker_order_id in self.kept:
            self.messages.append(f'cancel {broker_order_id} -> refused')
            raise RefusedRequestError.refusal(
                'the order is being modified at the exchange and cannot be cancelled yet',
                503,
                broker=broker_name,
            )
        return super().cancel(broker_name, broker_order_id)


class CancellingLegsAndParentsExample:
    """Cancels legs and parents every way the base class knows.

    Attributes:
        placement (StubbornPlacement): The stand-in placement.
    """

    def __init__(self):
        """Builds the stand-in placement.

        Returns:
            None: This method returns nothing.
        """
        self.placement = StubbornPlacement()

    def runner(self, legs):
        """A plain runner for a buy of 10 RELIANCE, with some legs placed.

        Args:
            legs (int): How many legs to place.

        Returns:
            SyntheticOrder: The runner.
        """
        intent = {
            'intent_id': 'intent-1',
            'instrument_id': INSTRUMENT_ID,
            'body': {
                'instrument_id': INSTRUMENT_ID,
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'price': '1000.00',
                'quantity': 10,
            },
        }
        runner = SyntheticOrder.started(
            intent,
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )
        if legs:
            runner.record_received()
            runner.record_state('working', None)
            order = runner.read_order(runner.parent.body)
            for _ in range(legs):
                runner.place_leg('entry', order, time.perf_counter())
        return runner

    def finished(self, runner, leg):
        """Records the broker reporting a leg cancelled.

        Args:
            runner (SyntheticOrder): The runner.
            leg (OrderLeg): The leg.

        Returns:
            None: This method returns nothing.
        """
        runner.record({
            'event': 'leg_update',
            'parent_state': runner.parent.state,
            'leg_id': leg.leg_id,
            'leg_role': leg.role,
            'leg_state': 'cancelled',
        })

    def run(self):
        """Cancels every way and prints what each did.

        Returns:
            None: This method returns nothing.
        """
        runner = self.runner(2)
        first, second = runner.parent.legs
        self.placement.kept.add(second.broker_order_id)
        print(f"cancel_leg: accepted {runner.cancel_leg(first, 'no longer wanted')}")
        outcome, message, response = runner.cancel_leg_answered(second, 'no longer wanted')
        print(f'cancel_leg_answered: {outcome}, {message}, {response}')

        caller = self.runner(2)
        resting, stubborn = caller.parent.legs
        self.placement.kept = {
            stubborn.broker_order_id,
        }
        answers = caller.cancel_by_caller('the caller cancelled the parent')
        for answer in answers:
            print(f"cancel_by_caller: {answer['order_id']} {answer['outcome']}")
        print(f'  parent {caller.parent.state}; finish_cancelling now: {caller.finish_cancelling()}')
        self.finished(caller, resting)
        self.finished(caller, stubborn)
        print(f'  both legs reported cancelled; finish_cancelling: {caller.finish_cancelling()}, parent {caller.parent.state}')

        quiet = self.runner(1)
        print(f"stop_acting: {quiet.stop_acting('flatten is closing everything')}, parent {quiet.parent.state}, again {quiet.stop_acting('flatten again')}")
        print(f"cancel_outside_order: accepted {quiet.cancel_outside_order('dhan', '52260930111', 'squaring off RELIANCE')}")

        refused = self.runner(0)
        refused.record_received()
        refused.abandon('the instrument has no agreed tick size')
        print(f'abandon after recording: parent {refused.parent.state}, {refused.parent.last_error}')
        untouched = self.runner(0)
        untouched.abandon('a dry run that was refused')
        print(f'abandon with nothing recorded: parent {untouched.parent.state}, events {len(untouched.event_log.events)}')
        print('Sent to the brokers, in order:')
        for message in self.placement.messages:
            print(f'  {message}')


if __name__ == '__main__':
    CancellingLegsAndParentsExample().run()
