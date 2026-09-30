"""Fills a paper virtual limit order from the queue estimate, and calls the rest of the type's steps by hand.

With `paper: true`, a `VirtualLimit` order is never sent. On each price tick it reads the queue estimate that `bin/unified/orders/virtual_book` keeps and records whatever more a resting order would have filled, as a `paper_filled` event at the limit price; the parent completes when the whole quantity has filled. This program sells 60 INFY at 1,510.00 on paper. The estimate says 25 filled, then 60, and the program prints the parent after each tick. Changing its quantity to 20, below the 25 already filled, is refused.

It also calls the steps directly on a real (not paper) order: `watched_price` reads the best bid for a sell and nothing from a stale quote, `child_order` builds the limit at the order's own price, `estimate` reads the queue estimate, and `fire` sends the order and records the missed quantity. Last, a market order is refused by `read_level` with HTTP 400, because a virtual limit is held at its own limit price.

The queue estimate normally lives in the Redis hash `unified:orders:virtual_queue`; a stand-in cache serves it. The placement is a stand-in that chooses Zerodha and accepts every order; the event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/virtual_limit/VirtualLimit/example_2_paper_fills_from_the_queue.py
"""

import decimal
import json
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
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.virtual_limit import (
    VirtualLimit,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000002'


class QueueEstimateCache:
    """Stands in for Redis, holding one queue estimate for whichever order asks.

    Attributes:
        estimate (dict): The estimate `virtual_book` would have written.
    """

    def __init__(self, estimate):
        """Builds the cache.

        Args:
            estimate (dict): The estimate to serve.

        Returns:
            None: This method returns nothing.
        """
        self.estimate = estimate

    def hget(self, key, field):
        """Reads one field of a hash, which is only ever the queue estimates.

        Args:
            key (str): The key, `unified:orders:virtual_queue`.
            field (str): The parent order id, which the stand-in does not need.

        Returns:
            str | None: The estimate as JSON, or None for any other key.
        """
        del field
        if key != 'unified:orders:virtual_queue':
            return None
        return json.dumps(self.estimate)


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


class PaperFillsFromTheQueueExample:
    """Fills a paper order and calls the other steps by hand.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
    """

    def __init__(self):
        """Builds the stand-in placement with an estimate of 25 filled.

        Returns:
            None: This method returns nothing.
        """
        self.placement = StandInPlacement()
        self.placement.cache = QueueEstimateCache({
            'queue_ahead': 120,
            'queue_filled': 145,
            'filled': 25,
        })

    def runner(self, order_type, synthetic):
        """A virtual limit selling 60 INFY, with its intent.

        Args:
            order_type (str): `LIMIT` or `MARKET`.
            synthetic (dict): The order type's parameters.

        Returns:
            tuple: The runner (VirtualLimit) and its intent (dict).
        """
        body = {
            'instrument_id': INSTRUMENT_ID,
            'transaction_type': 'SELL',
            'product': 'MIS',
            'order_type': order_type,
            'quantity': 60,
            'synthetic': synthetic,
        }
        if order_type == 'LIMIT':
            body['price'] = '1510.00'
        intent = {
            'intent_id': 'intent-1',
            'instrument_id': INSTRUMENT_ID,
            'body': body,
        }
        runner = VirtualLimit.started(
            intent,
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )
        return runner, intent

    def book(self, stale):
        """A book bid 1,508.00 and offered 1,508.50.

        Args:
            stale (bool): Whether the quote is marked stale.

        Returns:
            dict: The quote.
        """
        return {
            'last_price': 1508.20,
            'stale': stale,
            'depth': {
                'buy': [
                    {
                        'price': 1508.00,
                        'quantity': 200,
                        'orders': 2,
                    },
                ],
                'sell': [
                    {
                        'price': 1508.50,
                        'quantity': 200,
                        'orders': 2,
                    },
                ],
            },
        }

    def run(self):
        """Fills the paper order, calls the steps, and prints the refusal.

        Returns:
            None: This method returns nothing.
        """
        paper, intent = self.runner(
            'LIMIT',
            {
                'type': 'virtual_limit',
                'paper': True,
            },
        )
        paper.run(intent, time.perf_counter())
        print(f'Paper order: is_paper {paper.is_paper()}')
        paper.on_price_tick({}, 1790000000.0)
        print(f"After the estimate says 25: paper_filled {paper.parent.parameters['paper_filled']}, parent {paper.parent.state}")
        try:
            paper.modify_held(None, 20, False)
        except RefusedRequestError as refusal:
            print(f"Changing it to 20: HTTP {refusal.status}, {refusal.body['error']}")
        self.placement.cache.estimate['filled'] = 60
        paper.fill_on_paper()
        print(f"After the estimate says 60: paper_filled {paper.parent.parameters['paper_filled']}, parent {paper.parent.state}, {paper.parent.last_error}")
        print(f'Sent to the broker for the paper order: {self.placement.messages}')

        real, intent = self.runner(
            'LIMIT',
            {
                'type': 'virtual_limit',
            },
        )
        real.run(intent, time.perf_counter())
        tick_size = decimal.Decimal('0.05')
        print(f'watched_price: {real.watched_price(MarketView(self.book(False), tick_size))}, from a stale quote: {real.watched_price(MarketView(self.book(True), tick_size))}')
        order = real.read_order(real.parent.body)
        child = real.child_order(order, None)
        print(f'child_order: {child.transaction_type} {child.quantity} {child.order_type} at {child.price}')
        print(f"estimate: {real.estimate()}")
        real.fire(child, decimal.Decimal('1510.00'), real.read_level())
        print(f"fire: sent {self.placement.messages}, missed_quantity {real.parent.parameters['missed_quantity']}")

        market, _ = self.runner(
            'MARKET',
            {
                'type': 'virtual_limit',
            },
        )
        try:
            market.read_level()
        except RefusedRequestError as refusal:
            print(f"A market order: HTTP {refusal.status}, {refusal.body['error']}")


if __name__ == '__main__':
    PaperFillsFromTheQueueExample().run()
