"""Shows a two-sided quote stop quoting the side that would pass its inventory cap, and reads its settings and fair price by hand.

When the net position a `TwoSidedQuote` has built reaches `most_inventory`, the side that would add to it is not quoted again until the position comes back, as a grid does. This program quotes 20 INFY around the last traded price (`fair_price: last`) with a half spread of 1.00 and `most_inventory` of 20. The ask fills, so the position is short 20, at its cap: the next tick re-prices the bid but does not quote the ask again. A tick on a quote marked stale does nothing at all.

It also calls the readers directly: `read_positive` and `read_whole` read numbers from the parameters, `read_fair_price_kind` the fair price, `wanted_prices` where the bid and ask belong for a view of the book, and `live_quote` the resting order on each side. Last, three settings are refused with HTTP 400: a missing half spread, a step of zero ticks, and a fair price of `vwap`.

The placement is a stand-in that serves the first book, chooses Zerodha and accepts every order and change; the event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine. The fill is recorded as the `leg_update` event the engine's order update follower writes.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/two_sided_quote/TwoSidedQuote/example_2_inventory_cap_and_settings.py
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
from unified_broker_interface.utilities.order_engine.two_sided_quote import (
    TwoSidedQuote,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
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


class InventoryCapAndSettingsExample:
    """Runs a capped two-sided quote, reads its settings, and prints refusals.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
    """

    def __init__(self):
        """Builds the stand-in placement with INFY last traded at 1,500.

        Returns:
            None: This method returns nothing.
        """
        self.placement = StandInPlacement(
            quotes={
                INSTRUMENT_ID: self.book(1500.00, False),
            },
        )

    def book(self, last_price, stale):
        """A book around a last traded price.

        Args:
            last_price (float): The last traded price.
            stale (bool): Whether the quote is marked stale.

        Returns:
            dict: The quote.
        """
        return {
            'last_price': last_price,
            'stale': stale,
            'depth': {
                'buy': [
                    {
                        'price': round(last_price - 0.10, 2),
                        'quantity': 300,
                        'orders': 3,
                    },
                ],
                'sell': [
                    {
                        'price': round(last_price + 0.20, 2),
                        'quantity': 300,
                        'orders': 3,
                    },
                ],
            },
        }

    def runner(self, synthetic):
        """A two-sided quote on 20 INFY, with its intent.

        Args:
            synthetic (dict): The order type's parameters.

        Returns:
            tuple: The runner (TwoSidedQuote) and its intent (dict).
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
                'quantity': 20,
                'synthetic': synthetic,
            },
        }
        runner = TwoSidedQuote.started(
            intent,
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )
        return runner, intent

    def run(self):
        """Runs the capped quote, reads its settings, and prints refusals.

        Returns:
            None: This method returns nothing.
        """
        runner, intent = self.runner({
            'type': 'two_sided_quote',
            'half_spread_points': 1,
            'most_inventory': 20,
            'fair_price': 'last',
        })
        runner.run(intent, time.perf_counter())
        print(f"half_spread_points {runner.read_positive('half_spread_points', True)}, skew_ticks {runner.read_whole('skew_ticks', 0, 0)}, fair price {runner.read_fair_price_kind()}")
        view = MarketView(self.book(1500.00, False), runner.tick_size())
        print(f'wanted_prices: {runner.wanted_prices(view)}')
        ask = runner.live_quote('ask')
        runner.record({
            'event': 'leg_update',
            'parent_state': runner.parent.state,
            'leg_id': ask.leg_id,
            'leg_role': ask.role,
            'leg_state': 'filled',
            'filled_quantity': 20,
        })
        print(f'The ask filled: inventory {runner.inventory()}, past its cap {runner.past_its_cap()}')
        acted = runner.on_price_tick(
            {
                INSTRUMENT_ID: self.book(1498.00, True),
            },
            1790000000.0,
        )
        print(f'A stale tick: acted {acted}')
        acted = runner.on_price_tick(
            {
                INSTRUMENT_ID: self.book(1498.00, False),
            },
            1790000001.0,
        )
        print(f"Last 1498: acted {acted}, bid {runner.live_quote('bid').price}, ask {runner.live_quote('ask')}")
        print('Sent to the broker:')
        for message in self.placement.messages:
            print(f'  {message}')

        mistakes = [
            (
                'No half spread',
                {
                    'type': 'two_sided_quote',
                    'most_inventory': 20,
                },
                'half_spread_points',
            ),
            (
                'A step of zero ticks',
                {
                    'type': 'two_sided_quote',
                    'step_ticks': 0,
                },
                'step_ticks',
            ),
            (
                'A fair price of vwap',
                {
                    'type': 'two_sided_quote',
                    'fair_price': 'vwap',
                },
                'fair_price',
            ),
        ]
        for heading, synthetic, setting in mistakes:
            careless, _ = self.runner(synthetic)
            try:
                if setting == 'half_spread_points':
                    careless.read_positive('half_spread_points', True)
                elif setting == 'step_ticks':
                    careless.read_whole('step_ticks', 1, 1)
                else:
                    careless.read_fair_price_kind()
            except RefusedRequestError as refusal:
                print(f"{heading}: HTTP {refusal.status}, {refusal.body['error']}")
        print(f"read_positive for a setting not given and not required: {careless.read_positive('offset_points', False)}")
        print(f"Tick size used: {decimal.Decimal(runner.parent.parameters['tick_size'])}")


if __name__ == '__main__':
    InventoryCapAndSettingsExample().run()
