"""Calls a buying chaser's steps directly, and shows it carrying on from a price the caller set.

`Chaser.on_price_tick` decides when to move; underneath are the pieces this program calls one at a time on a chaser buying ten RELIANCE with no cap and no time to cross:

- `capped` holds a price back at a limit, which a buy applies as a maximum;
- `priced` turns the caller's order into a limit at a worked-out price;
- `step` moves the resting order one step towards the offer, but never past it;
- `cross` moves it straight to the offer, where it trades;
- `on_leg_modified` is what the engine calls after a caller changes the order through `PUT /api/orders/modify`: it restarts the wait before the next step from now, and records the parameters so a restart keeps them.

It also shows that `should_cross` is never true without `cross_after_seconds`, and that a step of zero ticks is refused with HTTP 400.

The placement is a stand-in that serves a quote, chooses Zerodha and accepts every order and change; the event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine. The caller's change is recorded as the `leg_update` event `apply_outside_modification` writes, so the leg holds the new price when `on_leg_modified` is called.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/chaser/Chaser/example_2_steps_and_caller_change.py
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
from unified_broker_interface.utilities.order_engine.chaser import (
    Chaser,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
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


class StepsAndCallerChangeExample:
    """Drives a buying chaser's steps by hand.

    Attributes:
        quote (dict): The live quote.
        placement (StandInPlacement): The stand-in placement.
    """

    def __init__(self):
        """Builds the stand-in placement with RELIANCE bid 1,000.00 and offered 1,000.15.

        Returns:
            None: This method returns nothing.
        """
        self.quote = {
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
                        'price': 1000.15,
                        'quantity': 100,
                        'orders': 1,
                    },
                ],
            },
        }
        self.placement = StandInPlacement(
            quotes={
                INSTRUMENT_ID: self.quote,
            },
        )

    def runner(self, synthetic):
        """A chaser buying ten RELIANCE, built but not run.

        Args:
            synthetic (dict): The order type's parameters.

        Returns:
            Chaser: The runner.
        """
        return Chaser.started(
            self.intent(synthetic),
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )

    def intent(self, synthetic):
        """An intent buying ten RELIANCE.

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
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'price': 1000,
                'quantity': 10,
                'synthetic': synthetic,
            },
        }

    def run(self):
        """Steps, crosses and takes a caller's change, then prints a refusal.

        Returns:
            None: This method returns nothing.
        """
        synthetic = {
            'type': 'chaser',
            'step_ticks': 1,
        }
        runner = self.runner(synthetic)
        runner.run(self.intent(synthetic), time.perf_counter())
        leg = runner.working_leg()
        print(f'Placed at the bid: {leg.price}')
        print(f"capped(1001.30, BUY, 1001.00): {runner.capped(decimal.Decimal('1001.30'), 'BUY', decimal.Decimal('1001.00'))}")
        order = runner.read_order(runner.parent.body)
        priced = runner.priced(order, decimal.Decimal('999.95'))
        print(f'priced: {priced.transaction_type} {priced.quantity} {priced.order_type} at {priced.price}')

        view = MarketView(self.quote, runner.tick_size())
        started = runner.parent.parameters['started_walking_at']
        for number in (
            1,
            2,
            3,
            4,
        ):
            moved = runner.step(leg, view, started + number)
            print(f'step {number}: moved {moved}, price {leg.price}')
        print(f'should_cross without cross_after_seconds: {runner.should_cross(started + 3600)}')

        before = {
            'quantity': leg.quantity,
            'price': leg.price,
            'trigger_price': leg.trigger_price,
        }
        runner.record({
            'event': 'leg_update',
            'parent_state': runner.parent.state,
            'leg_id': leg.leg_id,
            'leg_role': leg.role,
            'price': 999.50,
        })
        runner.on_leg_modified(leg, before)
        print(f"Caller moved it to {leg.price}; the step wait restarted: {runner.parent.parameters['stepped_at'] >= started}")
        print(f"Recorded: {runner.event_log.events[-1]['event']}, {runner.event_log.events[-1]['status_message']}")

        crossed = runner.cross(leg, view)
        print(f'cross: moved {crossed}, price {leg.price}')
        print('Sent to the broker:')
        for message in self.placement.messages:
            print(f'  {message}')

        refused = self.runner({
            'type': 'chaser',
            'step_ticks': 0,
        })
        try:
            refused.read_step_ticks()
        except RefusedRequestError as refusal:
            print(f"Zero ticks: HTTP {refusal.status}, {refusal.body['error']}")


if __name__ == '__main__':
    StepsAndCallerChangeExample().run()
