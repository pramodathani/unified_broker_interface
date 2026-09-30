"""Holds a limit buy in the engine's own book, changes its price while it is held, and sends it only once the offer reaches it.

A `VirtualLimit` order spends a broker's daily order message only when it will fill. It is held by the engine and sent, as a limit at the caller's own price, once the other side of the book reaches that price. What it gives up is the place in the queue, so when it is sent it records `missed_quantity`: how much a resting order at that price would have filled while this one was held, as `bin/unified/orders/virtual_book` estimated it.

This program holds a buy of 100 RELIANCE at 1,000.00. A tick with the best offer at 1,000.20 does nothing. The caller then moves the held order to 1,000.10 with `modify_held`, first as a dry run and then for real; nothing reaches a broker. When the offer comes down to 1,000.10 the order is sent at 1,000.10, and the estimate of 40 filled in the queue is recorded as missed. After that, changing it by parent id is refused, and the answer names the broker order to change instead.

The queue estimate normally lives in the Redis hash `unified:orders:virtual_queue`; a stand-in cache serves it. The placement is a stand-in that chooses Zerodha and accepts every order; the event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/virtual_limit/VirtualLimit/example_1_held_then_sent_when_offer_reaches_it.py
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
from unified_broker_interface.utilities.order_engine.virtual_limit import (
    VirtualLimit,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'


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


class HeldThenSentExample:
    """Holds a virtual limit buy, changes it, and lets the offer reach it.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
        intent (dict): The intent the REST API would have written.
        runner (VirtualLimit): The order type running the parent.
    """

    def __init__(self):
        """Builds the runner holding a buy of 100 RELIANCE at 1,000.00.

        Returns:
            None: This method returns nothing.
        """
        self.placement = StandInPlacement()
        self.placement.cache = QueueEstimateCache({
            'queue_ahead': 350,
            'queue_filled': 40,
            'filled': 0,
        })
        self.intent = {
            'intent_id': 'intent-1',
            'instrument_id': INSTRUMENT_ID,
            'body': {
                'instrument_id': INSTRUMENT_ID,
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'price': '1000.00',
                'quantity': 100,
                'synthetic': {
                    'type': 'virtual_limit',
                },
            },
        }
        self.runner = VirtualLimit.started(
            self.intent,
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )

    def tick(self, offer):
        """Feeds one price tick with the given best offer.

        Args:
            offer (float): The best offer.

        Returns:
            None: This method returns nothing.
        """
        fired = self.runner.on_price_tick(
            {
                INSTRUMENT_ID: {
                    'last_price': offer,
                    'depth': {
                        'buy': [
                            {
                                'price': round(offer - 0.10, 2),
                                'quantity': 500,
                                'orders': 4,
                            },
                        ],
                        'sell': [
                            {
                                'price': offer,
                                'quantity': 300,
                                'orders': 3,
                            },
                        ],
                    },
                },
            },
            1790000000.0,
        )
        print(f'Offer at {offer}: sent {fired}')

    def run(self):
        """Holds, changes and sends the order.

        Returns:
            None: This method returns nothing.
        """
        body, status = self.runner.run(self.intent, time.perf_counter())
        print(f"Run: HTTP {status}, outcome {body['outcome']}, paper {body['paper']} (is_paper {self.runner.is_paper()}), held at {self.runner.read_level()}")
        self.tick(1000.20)
        answer, status = self.runner.modify_held(decimal.Decimal('1000.10'), None, True)
        print(f"modify_held dry run: HTTP {status}, {answer['status_message']}")
        answer, status = self.runner.modify_held(decimal.Decimal('1000.10'), None, False)
        print(f"modify_held: HTTP {status}, {answer['outcome']}, now {answer['quantity']} at {answer['price']}; orders sent so far {len(self.placement.messages)}")
        held = self.runner.held_order()
        print(f'held_order: {held.transaction_type} {held.quantity} at {held.price}')
        self.tick(1000.10)
        print(f"Sent to the broker: {self.placement.messages}; missed_quantity {self.runner.parent.parameters['missed_quantity']}")
        try:
            self.runner.modify_held(decimal.Decimal('999.90'), None, False)
        except RefusedRequestError as refusal:
            print(f"modify_held after sending: HTTP {refusal.status}, {refusal.body['error']}; change broker {refusal.body['broker']} order {refusal.body['order_id']} instead")


if __name__ == '__main__':
    HeldThenSentExample().run()
