"""Shows `SyntheticOrder`'s market readers, the hooks a type overrides, how answers combine, and how a parent finishes.

Besides placing and changing legs, the base class gives every order type a few readers and defaults that this program calls directly:

- `remember_tick_size` works out the tick size the brokers agree on and keeps it on the parent as text, and `tick_size` reads it back; when the brokers disagree it refuses with HTTP 503, because a type that computes prices cannot run without one.
- `trading_segment` names the instrument's segment, `own_quote` picks the parent's own quote out of a tick, and `view` wraps a quote with the tick size.
- `on_leg_update`, `on_clock_tick` and `on_price_tick` do nothing in the base class; a type overrides the ones it needs.
- `combined_answer` turns several orders' outcomes into one answer: all accepted is 200, none accepted is `unknown` or `rejected`, and a mix is `partial` with 207.
- `finish_with_legs` ends a type that is done once its legs are: `completed` when anything traded and `cancelled` when nothing did, and nothing while a leg is still resting.
- `save` writes the parent to the Redis copy, and a failure there is logged rather than raised, because the event log still has everything.

The placement is a stand-in that serves a quote, chooses Zerodha and accepts every order; the event log is the `RecordingEventLog` stand-in; one parent store keeps nothing and another always fails. Nothing leaves the machine. Leg reports are recorded as the `leg_update` events the engine's order update follower writes.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/base/SyntheticOrder/example_4_market_readers_and_finishing.py
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
OTHER_ID = '11111111-1111-5111-8111-000000000002'


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


class DisagreeingPlacement(StandInPlacement):
    """The stand-in placement, with two brokers that publish different tick sizes for the instrument."""

    def market_context(self, instrument_id, needs_quote, needs_positions):
        """Answers with an instrument whose two brokers disagree on its tick size.

        Args:
            instrument_id (str): The instrument.
            needs_quote (bool): Unused.
            needs_positions (bool): Unused.

        Returns:
            tuple: The instrument (Instrument), no quote and no positions.
        """
        del needs_quote, needs_positions
        instrument = Instrument(
            instrument_id,
            {
                'segment': 'nse_equities',
            },
            {
                'zerodha': {
                    'order_symbol': 'SYMBOL',
                    'lot_size': 1,
                    'tick_size': '0.05',
                },
                'dhan': {
                    'order_symbol': 'SYMBOL',
                    'lot_size': 1,
                    'tick_size': '0.10',
                },
            },
        )
        return instrument, None, None


class FailingParentStore:
    """Stands in for a Redis copy of the parents that cannot be written."""

    def save(self, parent):
        """Refuses to keep a parent.

        Args:
            parent (ParentOrder): The parent.

        Returns:
            None: This method returns nothing.

        Raises:
            ConnectionError: Always.
        """
        del parent
        raise ConnectionError('Redis is not reachable')


class FinishesWithItsLegs(SyntheticOrder):
    """A type that is done once every order it placed is done, as a basket or a ladder is.

    Attributes:
        FINISHES_WITH_LEGS (bool): Always True for this type.
    """

    FINISHES_WITH_LEGS = True


class MarketReadersAndFinishingExample:
    """Calls the base class's readers, hooks, answers and finishing by hand.

    Attributes:
        logger (logging.Logger): The logger, which keeps the failed save's message out of the output.
        placement (StandInPlacement): The stand-in placement.
    """

    def __init__(self):
        """Builds the logger and the stand-in placement.

        Returns:
            None: This method returns nothing.
        """
        self.logger = logging.getLogger('example')
        self.logger.addHandler(logging.NullHandler())
        self.logger.propagate = False
        self.placement = StandInPlacement(
            quotes={
                INSTRUMENT_ID: {
                    'last_price': 1000.10,
                    'depth': {
                        'buy': [
                            {
                                'price': 1000.00,
                                'quantity': 100,
                                'orders': 1,
                            },
                        ],
                        'sell': [
                            {
                                'price': 1000.20,
                                'quantity': 100,
                                'orders': 1,
                            },
                        ],
                    },
                },
            },
        )

    def runner(self, order_class, placement, parent_store):
        """A runner for a buy of 10 RELIANCE.

        Args:
            order_class (type): `SyntheticOrder` or a subclass.
            placement (StandInPlacement): The placement to use.
            parent_store (object): The Redis copy of the parents to use.

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
        return order_class.started(
            intent,
            placement,
            RecordingEventLog(),
            parent_store,
            self.logger,
        )

    def finish(self, runner, leg, state, filled_quantity):
        """Records the broker reporting a leg finished.

        Args:
            runner (SyntheticOrder): The runner.
            leg (OrderLeg): The leg.
            state (str): `filled` or `cancelled`.
            filled_quantity (int): How much of it filled.

        Returns:
            None: This method returns nothing.
        """
        runner.record({
            'event': 'leg_update',
            'parent_state': runner.parent.state,
            'leg_id': leg.leg_id,
            'leg_role': leg.role,
            'leg_state': state,
            'filled_quantity': filled_quantity,
        })

    def run(self):
        """Calls each reader, hook and finishing step, and prints what it gives.

        Returns:
            None: This method returns nothing.
        """
        runner = self.runner(SyntheticOrder, self.placement, StandInParentStore())
        order = runner.read_order(runner.parent.body)
        print(f'tick_size before remembering: {runner.tick_size()}; remember_tick_size: {runner.remember_tick_size(order)}; kept as {runner.parent.parameters}')
        print(f'trading_segment: {runner.trading_segment()}')
        quotes = {
            INSTRUMENT_ID: self.placement.quotes[INSTRUMENT_ID],
            OTHER_ID: None,
        }
        print(f"own_quote last price: {runner.own_quote(quotes)['last_price']}; view: bid {runner.view(quotes).best_bid()}, offer {runner.view(quotes).best_offer()}, other instrument readable {runner.view(quotes, OTHER_ID).is_readable()}")
        print(f'on_clock_tick: {runner.on_clock_tick(1790000000.0)}, on_price_tick: {runner.on_price_tick(quotes, 1790000000.0)}, on_leg_update: {runner.on_leg_update(None, {})}')
        disagreeing = self.runner(SyntheticOrder, DisagreeingPlacement(), StandInParentStore())
        try:
            disagreeing.remember_tick_size(order)
        except RefusedRequestError as refusal:
            print(f"remember_tick_size when brokers disagree: HTTP {refusal.status}, {refusal.body['error']}")

        cases = [
            (
                [
                    'accepted',
                    'accepted',
                ],
                [
                    200,
                    200,
                ],
            ),
            (
                [
                    'accepted',
                    'rejected',
                ],
                [
                    200,
                    400,
                ],
            ),
            (
                [
                    'rejected',
                    'unknown',
                ],
                [
                    400,
                    504,
                ],
            ),
            (
                [
                    'rejected',
                    'rejected',
                ],
                [
                    400,
                    409,
                ],
            ),
        ]
        for outcomes, statuses in cases:
            print(f'combined_answer {outcomes}: {runner.combined_answer(outcomes, statuses)}')

        for filled_quantity in (
            10,
            0,
        ):
            finishing = self.runner(FinishesWithItsLegs, self.placement, StandInParentStore())
            finishing.record_received()
            finishing.record_state('working', None)
            for _ in range(2):
                finishing.place_leg('entry', order, time.perf_counter())
            first, second = finishing.parent.legs
            self.finish(finishing, first, 'cancelled', 0)
            print(f'One leg finished: finish_with_legs {finishing.finish_with_legs()}, parent {finishing.parent.state}')
            if filled_quantity:
                self.finish(finishing, second, 'filled', filled_quantity)
            else:
                self.finish(finishing, second, 'cancelled', 0)
            print(f'Both finished, {filled_quantity} traded: finish_with_legs {finishing.finish_with_legs()}, parent {finishing.parent.state}, {finishing.parent.last_error}')

        failing = self.runner(SyntheticOrder, self.placement, FailingParentStore())
        failing.record_received()
        failing.save()
        print(f'save with Redis down: no exception, and the event log still has {len(failing.event_log.events)} event')


if __name__ == '__main__':
    MarketReadersAndFinishingExample().run()
