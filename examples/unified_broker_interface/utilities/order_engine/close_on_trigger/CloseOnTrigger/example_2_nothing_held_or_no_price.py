"""Fires a close-on-trigger order by hand when there is nothing to close, and when the book gives no price to close at.

`CloseOnTrigger.fire` is what a price tick calls once the level is reached. It closes what is held at that moment, not a quantity named in advance, so two endings are possible without any exit being sent:

- the position was closed some other way before the level was reached, so the parent is `completed` with nothing sent;
- a position is held but the book is empty on the side the exit would trade against, so the parent is `failed`, which asks a person to look.

This program calls `child_order`, which hands back the caller's own order because it only says which side and product the position was opened on, and then `fire` directly for each case, on long positions opened with a BUY on the `MIS` product. It also prints how `position_product` names each of the three products on the vocabulary the positions document uses.

A stand-in cache answers that no orders are resting, and the stand-in placement serves the positions and quotes for each case, chooses Zerodha and accepts every order. The event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/close_on_trigger/CloseOnTrigger/example_2_nothing_held_or_no_price.py
"""

import decimal
import json
import logging

from test_runs.engine_stand_ins import (
    RecordingEventLog,
)
from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.order_engine.close_on_trigger import (
    CloseOnTrigger,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000002'


class EmptyOrderUpdatesCache:
    """Stands in for Redis, with no order resting anywhere."""

    def hgetall(self, key):
        """Reads the whole of one hash, which is always empty.

        Args:
            key (str): The key, unused.

        Returns:
            dict: An empty hash.
        """
        del key
        return {}


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


class NothingHeldOrNoPriceExample:
    """Fires two close-on-trigger orders by hand and prints how each ended."""

    def runner(self, product, quantity_held, quote):
        """A close-on-trigger order guarding a long in INFY, built but not run.

        Args:
            product (str): The order's product, `CNC`, `MIS` or `NRML`.
            quantity_held (int): The net position the positions document shows.
            quote (dict): The live quote.

        Returns:
            CloseOnTrigger: The runner.
        """
        placement = StandInPlacement(
            quotes={
                INSTRUMENT_ID: quote,
            },
            positions={
                'net': [
                    {
                        'instrument_id': INSTRUMENT_ID,
                        'product': 'intraday',
                        'quantity': quantity_held,
                    },
                ],
                'day': [],
            },
        )
        placement.cache = EmptyOrderUpdatesCache()
        placement.cache = BrokerPositionsRedis(placement.cache, placement.positions)
        intent = {
            'intent_id': 'intent-1',
            'instrument_id': INSTRUMENT_ID,
            'body': {
                'instrument_id': INSTRUMENT_ID,
                'transaction_type': 'BUY',
                'product': product,
                'order_type': 'LIMIT',
                'price': '1500.00',
                'quantity': 40,
                'synthetic': {
                    'type': 'close_on_trigger',
                    'trigger_price': 1450,
                },
            },
        }
        return CloseOnTrigger.started(
            intent,
            placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )

    def fire(self, runner):
        """Fires a runner as a price tick at 1,449.00 would.

        Args:
            runner (CloseOnTrigger): The runner.

        Returns:
            None: This method returns nothing.
        """
        order = runner.read_order(runner.parent.body)
        child = runner.child_order(order, None)
        print(f'  child_order is the caller order itself: {child is order}')
        runner.fire(child, decimal.Decimal('1449.00'), decimal.Decimal('1450'))
        print(f'  orders sent: {runner.placement.messages}')
        print(f'  parent {runner.parent.state}: {runner.parent.last_error}')

    def run(self):
        """Prints the product names and fires both cases.

        Returns:
            None: This method returns nothing.
        """
        quote = {
            'last_price': 1449.00,
            'depth': {
                'buy': [
                    {
                        'price': 1448.90,
                        'quantity': 60,
                        'orders': 2,
                    },
                ],
                'sell': [
                    {
                        'price': 1449.10,
                        'quantity': 60,
                        'orders': 2,
                    },
                ],
            },
        }
        for product in (
            'CNC',
            'MIS',
            'NRML',
        ):
            runner = self.runner(product, 0, quote)
            print(f'{product} positions are read as {runner.position_product(runner.read_order(runner.parent.body))}')

        print('Position already closed:')
        self.fire(self.runner('MIS', 0, quote))

        empty_book = {
            'depth': {
                'buy': [],
                'sell': [],
            },
        }
        print('Forty held, but the book is empty:')
        self.fire(self.runner('MIS', 40, empty_book))


if __name__ == '__main__':
    NothingHeldOrNoPriceExample().run()
