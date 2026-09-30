"""Marks a calendar spread's legs to the market by hand, closes it at its profit target, and shows the limits it refuses.

A `StrategyStop` is built from steps that this program calls directly on a Nifty calendar spread, a sold near-month future and a bought far-month future of 75 units each, with a `profit_target` of 1,500:

- `leg_profit` marks one filled leg to its last price, counting a fall as a gain on the sold leg;
- `total_profit` adds the legs up and says whether every filled leg could be marked;
- `exit_order` builds the order that closes one leg, two ticks past the touch;
- `close_everything` closes the short leg first and then the long one, and ends the parent as `completed`;
- `number` reads one of the caller's levels, and `read_limits` refuses a `loss_limit` that is not below zero, with HTTP 400.

The placement is a stand-in that chooses Zerodha and accepts every order; the event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine. Fills are recorded as the `leg_update` events the engine's order update follower writes.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/strategy_stop/StrategyStop/example_2_marking_legs_by_hand.py
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
from unified_broker_interface.utilities.order_engine.strategy_stop import (
    StrategyStop,
)

NEAR_FUTURE = '11111111-1111-5111-8111-000000000009'
FAR_FUTURE = '11111111-1111-5111-8111-000000000028'


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

    def prepare(self, order, instrument_id, broker_name=None, legs=None):
        """Chooses a broker and builds the request, without sending it.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument_id (str): The instrument.
            broker_name (str | None): The broker the order must go to, or None for Zerodha.
            legs (OrderLegs | None): Every leg of the basket, which this stand-in does not check.

        Returns:
            StandInPreparedPlacement: The prepared order.
        """
        del legs
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


class MarkingLegsByHandExample:
    """Marks, closes and checks a calendar spread's strategy stop by hand.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
    """

    def __init__(self):
        """Builds the stand-in placement.

        Returns:
            None: This method returns nothing.
        """
        self.placement = StandInPlacement(tick_size='0.10')

    def runner(self, limits):
        """A strategy stop on the calendar spread, with its intent.

        Args:
            limits (dict): The loss and profit levels.

        Returns:
            tuple: The runner (StrategyStop) and its intent (dict).
        """
        synthetic = {
            'type': 'strategy_stop',
            'candidates': [
                {
                    'instrument_id': NEAR_FUTURE,
                    'transaction_type': 'SELL',
                    'price': '25000.00',
                },
                {
                    'instrument_id': FAR_FUTURE,
                    'price': '25150.00',
                },
            ],
        }
        synthetic.update(limits)
        intent = {
            'intent_id': 'intent-1',
            'instrument_id': NEAR_FUTURE,
            'body': {
                'instrument_id': NEAR_FUTURE,
                'transaction_type': 'BUY',
                'product': 'NRML',
                'order_type': 'LIMIT',
                'price': '25000.00',
                'quantity': 75,
                'synthetic': synthetic,
            },
        }
        runner = StrategyStop.started(
            intent,
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )
        return runner, intent

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
                        'quantity': 750,
                        'orders': 6,
                    },
                ],
            },
        }

    def run(self):
        """Marks the legs, closes the spread and prints a refusal.

        Returns:
            None: This method returns nothing.
        """
        runner, intent = self.runner({
            'profit_target': 1500,
        })
        runner.run(intent, time.perf_counter())
        print(f"number('profit_target'): {runner.number('profit_target')}, number('loss_limit'): {runner.number('loss_limit')}")
        for leg in runner.parent.legs:
            runner.record({
                'event': 'leg_update',
                'parent_state': runner.parent.state,
                'leg_id': leg.leg_id,
                'leg_role': leg.role,
                'leg_state': 'filled',
                'filled_quantity': 75,
                'average_price': leg.price,
            })
        quotes = {
            NEAR_FUTURE: self.quote(24960.00),
            FAR_FUTURE: self.quote(25132.00),
        }
        for leg in runner.parent.legs:
            print(f'leg_profit of the {leg.transaction_type} at {leg.average_price}: {runner.leg_profit(leg, quotes)}')
        total, complete = runner.total_profit(quotes)
        print(f'total_profit: {total}, every leg marked {complete}')
        for leg in runner.parent.legs:
            order = runner.exit_order(leg, quotes)
            print(f'exit_order for the {leg.transaction_type}: {order.transaction_type} {order.quantity} at {order.price}, product {order.product}')
        runner.close_everything(quotes, f'the strategy is up {total}, past its target of 1500')
        print('close_everything sent, in order:')
        for message in self.placement.messages[2:]:
            print(f'  {message}')
        print(f'Parent: {runner.parent.state}, {runner.parent.last_error}')

        careless, _ = self.runner({
            'loss_limit': 2000,
        })
        try:
            careless.read_limits()
        except RefusedRequestError as refusal:
            print(f"A loss_limit of 2000: HTTP {refusal.status}, {refusal.body['error']}")


if __name__ == '__main__':
    MarkingLegsByHandExample().run()
