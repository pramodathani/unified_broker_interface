"""Flips a long Nifty future position to a short when the price falls to a level: close first, and reverse once the close has filled.

A `StopAndReverse` order waits for a price and then turns the position it guards the other way: a long of 75 becomes a short of 75. It first cancels every order resting on the instrument, which frees the margin the new side needs. With the default `method` of `sequential` it then sends a closing order, and only when that has completely filled does it send a second order of the same size and side to open the reverse.

This program guards a long of 75 Nifty futures, opened with a BUY on the `NRML` product, with a level of 24,900. A tick at 24,950 does nothing. A tick at 24,895 fires: the target resting on the future is cancelled and a sell of 75 goes out two ticks under the best bid. When that sell is reported filled, a second sell of 75 opens the short.

The positions, quotes and resting orders normally come from Redis; a stand-in cache holds the orders and the stand-in placement serves the rest, chooses Zerodha and accepts every order and cancel. The event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine. The fill is recorded as the `leg_update` event the engine's order update follower writes and handed to `on_leg_update`.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/stop_and_reverse/StopAndReverse/example_1_close_then_reverse.py
"""

import json
import logging
import time

from test_runs.engine_stand_ins import (
    RecordingEventLog,
)
from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.order_engine.stop_and_reverse import (
    StopAndReverse,
)

FUTURE_ID = '11111111-1111-5111-8111-000000000009'


class OrderUpdatesCache:
    """Stands in for Redis, holding only the latest update of every order.

    Attributes:
        orders (list): The order updates, on the order contract.
    """

    def __init__(self, orders):
        """Builds the cache.

        Args:
            orders (list): The order updates.

        Returns:
            None: This method returns nothing.
        """
        self.orders = orders

    def hgetall(self, key):
        """Reads the whole of one hash, which is only ever the order updates.

        Args:
            key (str): The key, `unified:order-updates`.

        Returns:
            dict: `broker:order_id` to the update as JSON.
        """
        stored = {}
        if key != 'unified:order-updates':
            return stored
        for order in self.orders:
            stored[f"{order['broker']}:{order['order_id']}"] = json.dumps(order)
        return stored


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


class BrokerPositionsRedis:
    """Stands in for Redis as the position closer reads it: the order updates from another stand-in, and Zerodha's own positions and the token lookup, made from the positions document.

    The position closer reads each broker's `<broker>:portfolio:positions` hash rather than the unified positions document, because a closing order has to go to the broker that holds the position, and it finds each position's instrument from the broker's token in `unified:broker_tokens`. Here every position is held at Zerodha, and an instrument's token is its own id.

    Attributes:
        inner (object): The stand-in that holds the order updates.
        positions (dict | None): The unified positions document the program set up.
    """

    PRODUCT_CODES = {
        'intraday': 'MIS',
        'delivery': 'CNC',
        'carry': 'NRML',
        'carryforward': 'NRML',
    }

    def __init__(self, inner, positions):
        """Builds the stand-in.

        Args:
            inner (object): The stand-in that holds the order updates.
            positions (dict | None): The unified positions document.

        Returns:
            None: This method returns nothing.
        """
        self.inner = inner
        self.positions = positions

    def hgetall(self, key):
        """Reads a whole hash: Zerodha's positions, or whatever the inner stand-in holds.

        Args:
            key (str): The key.

        Returns:
            dict: The hash's fields and values.
        """
        if key != 'zerodha:portfolio:positions':
            return self.inner.hgetall(key)
        entries = {}
        for row in (self.positions or {}).get('net') or []:
            code = self.PRODUCT_CODES.get(row['product'], row['product'].upper())
            entries[f"NET:{row['instrument_id']}:{code}"] = json.dumps({
                'position': {
                    'instrument_token': row['instrument_id'],
                    'product': code,
                    'quantity': row['quantity'],
                    'day_or_net': 'NET',
                },
            })
        return entries

    def hget(self, key, field):
        """Reads one field, which is only ever a token in `unified:broker_tokens`.

        Args:
            key (str): The key.
            field (str): `broker:token`.

        Returns:
            str | None: The instruments the token names, as JSON, or None.
        """
        if key != 'unified:broker_tokens' or not field.startswith('zerodha:'):
            return None
        return json.dumps([
            field.split(':', 1)[1],
        ])

    def pipeline(self, transaction=True):
        """A pipeline that answers each queued read from this stand-in.

        Args:
            transaction (bool): Unused.

        Returns:
            StandInPipeline: The pipeline.
        """
        del transaction
        return StandInPipeline(self)


class StandInPipeline:
    """Stands in for a Redis pipeline, queueing reads and answering them all at once.

    Attributes:
        redis (BrokerPositionsRedis): The stand-in the reads are answered from.
        keys (list): The hashes queued, in order.
    """

    def __init__(self, redis):
        """Builds an empty pipeline.

        Args:
            redis (BrokerPositionsRedis): The stand-in the reads are answered from.

        Returns:
            None: This method returns nothing.
        """
        self.redis = redis
        self.keys = []

    def hgetall(self, key):
        """Queues reading a whole hash.

        Args:
            key (str): The key.

        Returns:
            None: This method returns nothing.
        """
        self.keys.append(key)

    def execute(self):
        """Answers every queued read.

        Returns:
            list: One hash per queued read, in order.
        """
        answers = []
        for key in self.keys:
            answers.append(self.redis.hgetall(key))
        return answers


class StandInOrderPlacement:
    """Stands in for the order placement, which names the brokers the system trades with.

    Attributes:
        broker_names (list): The brokers, which here is only Zerodha.
    """

    def __init__(self):
        """Builds the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.broker_names = [
            'zerodha',
        ]


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
        order_placement (StandInOrderPlacement): Names the brokers the system trades with.
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
        self.order_placement = StandInOrderPlacement()
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


class CloseThenReverseExample:
    """Arms a sequential stop-and-reverse on a long future and fires it.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
        intent (dict): The intent the REST API would have written.
        runner (StopAndReverse): The order type running the parent.
    """

    def __init__(self):
        """Builds the runner guarding a long of 75 Nifty futures at 24,900.

        Returns:
            None: This method returns nothing.
        """
        self.placement = StandInPlacement(
            quotes={
                FUTURE_ID: self.quote(24950.00),
            },
            positions={
                'net': [
                    {
                        'instrument_id': FUTURE_ID,
                        'product': 'carry',
                        'quantity': 75,
                    },
                ],
                'day': [],
            },
            tick_size='0.10',
        )
        self.placement.cache = OrderUpdatesCache([
            {
                'broker': 'zerodha',
                'order_id': '260930000901',
                'instrument_id': FUTURE_ID,
                'status': 'OPEN',
            },
        ])
        self.placement.cache = BrokerPositionsRedis(self.placement.cache, self.placement.positions)
        self.intent = {
            'intent_id': 'intent-1',
            'instrument_id': FUTURE_ID,
            'body': {
                'instrument_id': FUTURE_ID,
                'transaction_type': 'BUY',
                'product': 'NRML',
                'order_type': 'LIMIT',
                'price': '25000.00',
                'quantity': 75,
                'synthetic': {
                    'type': 'stop_and_reverse',
                    'trigger_price': 24900,
                },
            },
        }
        self.runner = StopAndReverse.started(
            self.intent,
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )

    def quote(self, last_price):
        """A quote with a bid and an offer one tick either side of the last trade.

        Args:
            last_price (float): The last traded price.

        Returns:
            dict: The quote.
        """
        return {
            'last_price': last_price,
            'depth': {
                'buy': [
                    {
                        'price': round(last_price - 0.10, 2),
                        'quantity': 750,
                        'orders': 6,
                    },
                ],
                'sell': [
                    {
                        'price': round(last_price + 0.10, 2),
                        'quantity': 600,
                        'orders': 5,
                    },
                ],
            },
        }

    def run(self):
        """Arms the order, fires it, and fills the close.

        Returns:
            None: This method returns nothing.
        """
        body, status = self.runner.run(self.intent, time.perf_counter())
        print(f"Run: HTTP {status}, outcome {body['outcome']}, fires {body['trigger_direction']} {body['trigger_level']}, method {self.runner.read_method()}")
        for last_price in (
            24950.00,
            24895.00,
        ):
            quote = self.quote(last_price)
            self.placement.quotes[FUTURE_ID] = quote
            fired = self.runner.on_price_tick(
                {
                    FUTURE_ID: quote,
                },
                1790000000.0,
            )
            print(f'Last {last_price}: fired {fired}')
        close = self.runner.parent.legs[0]
        changes = {
            'leg_state': 'filled',
            'filled_quantity': 75,
        }
        self.runner.record({
            'event': 'leg_update',
            'parent_state': self.runner.parent.state,
            'leg_id': close.leg_id,
            'leg_role': close.role,
            'leg_state': 'filled',
            'filled_quantity': 75,
        })
        self.runner.on_leg_update(close, changes)
        print(f'The close filled: {self.runner.parent.last_error}')
        print('Sent to the broker, in order:')
        for message in self.placement.messages:
            print(f'  {message}')


if __name__ == '__main__':
    CloseThenReverseExample().run()
