"""Changes a parent's legs through `SyntheticOrder` while the engine's risk gates watch every request.

Every change an order type makes to a resting leg passes the same checks: a move must actually move the order, the re-pricing throttle must allow it, the broker's daily order cap must have room for it, and the rate budget must give a token. Each refusal is recorded against the leg rather than raised, so the log shows why an order stayed where it was. This program places an entry and a stop on a plain runner built with a stand-in for the engine's `RiskGates`, and then:

1. `moves_the_price` tells a real move from one to where the order already is.
2. `reprice_leg` moves the entry; moving it again at once is refused by `allowed_to_reprice`, because the throttle wants two seconds between moves of one order.
3. With the day's cap nearly used, `has_room_today` refuses to move either leg, since neither is marked as closing a position; once the order's parameters say `closes_position`, as an order sent to get out of a position does, it allows them to use the part of the cap kept for exits.
4. With the rate budget empty, `take_rate_token` refuses; once it refills, `reduce_leg` cuts the entry to 6.
5. `release_daily_place` gives back the cap place counted for a message that was not sent.
6. `apply_outside_modification` sends a caller's change to the stop's trigger, which the base class allows (`outside_change_problem` has no objection) and then hands to `on_leg_modified`, which the base class leaves alone. `record_parameters` records the parameters so a restart keeps them.
7. `modify_held` refuses with HTTP 409, because a type that holds no order of its own changes its legs by broker and order id.

The placement is a stand-in that chooses Zerodha and accepts every order and change; the gates are a stand-in with switches the program flips; the event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/base/SyntheticOrder/example_3_changing_legs_under_the_gates.py
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


class StandInThrottle:
    """Stands in for the re-pricing throttle, which only needs to say its interval here.

    Attributes:
        minimum_seconds (float): How long one order must rest between moves.
    """

    def __init__(self):
        """Builds the throttle with a two-second interval.

        Returns:
            None: This method returns nothing.
        """
        self.minimum_seconds = 2.0


class StandInGates:
    """Stands in for the engine's risk gates, with switches instead of clocks and counters in Redis.

    Attributes:
        throttle (StandInThrottle): The re-pricing throttle.
        tokens_left (int): How many requests the rate budget still allows.
        capped (bool): Whether the day's cap has room only for exits.
        recently_moved (set): The legs moved too recently to move again.
        released (int): How many cap places were given back.
        sent (int): How many messages were counted as sent.
    """

    def __init__(self):
        """Builds gates that allow everything.

        Returns:
            None: This method returns nothing.
        """
        self.throttle = StandInThrottle()
        self.tokens_left = 100
        self.capped = False
        self.recently_moved = set()
        self.released = 0
        self.sent = 0

    def take_rate_token(self, broker_name):
        """Takes one request from the rate budget.

        Args:
            broker_name (str): The broker.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 429 when the budget is empty.
        """
        if self.tokens_left < 1:
            raise RefusedRequestError.refusal(
                f'the order rate budget for {broker_name} is full this second',
                429,
            )
        self.tokens_left = self.tokens_left - 1

    def refuse_if_capped(self, broker_name, closes_position):
        """Refuses an entry when the day's cap has room only for exits.

        Args:
            broker_name (str): The broker.
            closes_position (bool): Whether the request closes a position.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 429 for an entry while capped.
        """
        if self.capped and not closes_position:
            raise RefusedRequestError.refusal(
                f'{broker_name} has used its daily orders but the part kept for exits',
                429,
            )

    def release_reservation(self):
        """Gives back a cap place counted for a message that was not sent.

        Returns:
            None: This method returns nothing.
        """
        self.released = self.released + 1

    def count_sent(self, broker_name):
        """Counts one message as sent.

        Args:
            broker_name (str): The broker, unused.

        Returns:
            None: This method returns nothing.
        """
        del broker_name
        self.sent = self.sent + 1

    def allow_reprice(self, leg_id):
        """Whether a leg may be moved now.

        Args:
            leg_id (str): The leg.

        Returns:
            bool: False when it was moved too recently.
        """
        return leg_id not in self.recently_moved

    def record_reprice(self, leg_id):
        """Remembers that a leg was just moved.

        Args:
            leg_id (str): The leg.

        Returns:
            None: This method returns nothing.
        """
        self.recently_moved.add(leg_id)


class ChangingLegsUnderTheGatesExample:
    """Changes legs while the stand-in gates refuse and allow.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
        gates (StandInGates): The stand-in risk gates.
        runner (SyntheticOrder): The runner holding the legs.
    """

    def __init__(self):
        """Builds a runner with an entry and a stop resting.

        Returns:
            None: This method returns nothing.
        """
        self.placement = StandInPlacement()
        self.gates = StandInGates()
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
        self.runner = SyntheticOrder.started(
            intent,
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
            self.gates,
        )
        self.runner.record_received()
        self.runner.record_state('working', None)
        order = self.runner.read_order(self.runner.parent.body)
        self.runner.place_leg('entry', order, time.perf_counter())
        stop = order.with_quantities(10, 0)
        stop.transaction_type = 'SELL'
        stop.order_type = 'SL'
        stop.price = decimal.Decimal('988.00')
        stop.trigger_price = decimal.Decimal('990.00')
        self.runner.place_leg('stop', stop, time.perf_counter(), 'zerodha')

    def last_message(self):
        """The status message of the last event recorded.

        Returns:
            str | None: The message.
        """
        return self.runner.event_log.events[-1].get('status_message')

    def run(self):
        """Changes the legs step by step and prints what the gates allowed.

        Returns:
            None: This method returns nothing.
        """
        entry, stop = self.runner.parent.legs
        print(f"moves_the_price to 1000.00: {self.runner.moves_the_price(entry, decimal.Decimal('1000.00'), None)}, to 999.50: {self.runner.moves_the_price(entry, decimal.Decimal('999.50'), None)}")
        print(f"reprice_leg to 999.50: {self.runner.reprice_leg(entry, decimal.Decimal('999.50'), None, 'following the bid')}")
        print(f"reprice_leg again at once: {self.runner.reprice_leg(entry, decimal.Decimal('999.00'), None, 'following the bid')}; {self.last_message()}")
        print(f"allowed_to_reprice for the stop: {self.runner.allowed_to_reprice(stop, 'trailing')}")

        self.gates.capped = True
        print(f"has_room_today with the cap nearly used: entry {self.runner.has_room_today(entry, 'following the bid')}, stop {self.runner.has_room_today(stop, 'trailing')}")
        self.runner.parent.parameters = dict(self.runner.parent.parameters, closes_position=True)
        print(f"has_room_today once the order closes a position: entry {self.runner.has_room_today(entry, 'following the bid')}, stop {self.runner.has_room_today(stop, 'trailing')}")
        self.runner.parent.parameters = dict(self.runner.parent.parameters, closes_position=False)
        self.gates.capped = False

        self.gates.tokens_left = 0
        print(f"take_rate_token with the budget empty: {self.runner.take_rate_token(entry, 'reducing')}; {self.last_message()}")
        self.gates.tokens_left = 5
        print(f"reduce_leg to 6: {self.runner.reduce_leg(entry, 6, 'the caller wants less')}, entry now {entry.quantity}")
        self.runner.release_daily_place()
        print(f'release_daily_place: places given back {self.gates.released}')

        print(f'outside_change_problem for the stop: {self.runner.outside_change_problem(stop, None)}')
        outcome, message, response = self.runner.apply_outside_modification(stop, None, None, decimal.Decimal('992.00'))
        print(f'apply_outside_modification of the stop trigger to 992: {outcome}, trigger now {stop.trigger_price}')
        self.runner.on_leg_modified(
            stop,
            {
                'quantity': 10,
                'price': 988.0,
                'trigger_price': 990.0,
            },
        )
        self.runner.parent.parameters = {
            'caller_note': 'stop tightened',
        }
        self.runner.record_parameters('the caller tightened the stop')
        print(f"record_parameters: {self.runner.event_log.events[-1]['event']} with {self.runner.event_log.events[-1]['detail']['parameters']}")
        try:
            self.runner.modify_held(decimal.Decimal('999.00'), None, False)
        except RefusedRequestError as refusal:
            print(f"modify_held: HTTP {refusal.status}, {refusal.body['error']}")
        print(f'Messages counted as sent by the gates: {self.gates.sent}')
        print('Sent to the broker, in order:')
        for message in self.placement.messages:
            print(f'  {message}')


if __name__ == '__main__':
    ChangingLegsUnderTheGatesExample().run()
