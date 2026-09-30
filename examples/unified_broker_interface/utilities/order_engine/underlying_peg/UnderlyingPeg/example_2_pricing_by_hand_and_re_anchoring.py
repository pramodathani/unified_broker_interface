"""Works an underlying peg's price out by hand for a put offer, re-anchors it to a caller's change, and shows what it refuses.

An `UnderlyingPeg` is built from steps that this program calls directly on an offer of 50 units of a Nifty put at 80.00, with a delta of minus 0.4 and a `lowest_price` of 60, while the index stands at 25,000:

- `underlying` names the instrument followed, and `underlying_price` reads its last price from a tick's quotes;
- `number`, `read_range` and `read_step_ticks` read the settings;
- `target_price` works out where the offer belongs for an index of 25,030 (68.00) and of 24,900 (120.00), and one of 25,100 comes out at the floor of 60;
- `bounded` keeps any price inside the range and rounds it onto the tick, upwards for an offer, so 41.23 becomes the floor of 60 and 97.02 becomes 97.05;
- `on_leg_modified`, which the engine calls after a caller changes the price through `PUT /api/orders/modify` and the broker accepts, takes the caller's new price and the index's price at that moment as the new starting point.

Last, four refusals with HTTP 400: a peg on the traded instrument itself, a range upside down, a step of zero ticks, and a market order, which has no price to start from. The placement is a stand-in that serves the index's quote, chooses Zerodha and accepts every order; the event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/underlying_peg/UnderlyingPeg/example_2_pricing_by_hand_and_re_anchoring.py
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
from unified_broker_interface.utilities.order_engine.underlying_peg import (
    UnderlyingPeg,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)

PUT_ID = '11111111-1111-5111-8111-000000000015'
INDEX_ID = '11111111-1111-5111-8111-000000000012'


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


class PricingByHandAndReAnchoringExample:
    """Prices an underlying peg by hand, re-anchors it, and prints refusals.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
    """

    def __init__(self):
        """Builds the stand-in placement with the index at 25,000.

        Returns:
            None: This method returns nothing.
        """
        self.placement = StandInPlacement(
            quotes={
                INDEX_ID: {
                    'last_price': 25000.00,
                },
            },
        )

    def runner(self, order_type, synthetic, instrument_id=PUT_ID):
        """An underlying peg offering 50 units, with its intent.

        Args:
            order_type (str): `LIMIT` or `MARKET`.
            synthetic (dict): The order type's parameters.
            instrument_id (str): The instrument traded.

        Returns:
            tuple: The runner (UnderlyingPeg) and its intent (dict).
        """
        body = {
            'instrument_id': instrument_id,
            'transaction_type': 'SELL',
            'product': 'NRML',
            'order_type': order_type,
            'quantity': 50,
            'synthetic': synthetic,
        }
        if order_type == 'LIMIT':
            body['price'] = '80.00'
        intent = {
            'intent_id': 'intent-1',
            'instrument_id': instrument_id,
            'body': body,
        }
        runner = UnderlyingPeg.started(
            intent,
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )
        return runner, intent

    def settings(self, **changes):
        """The peg's settings, with some changed.

        Args:
            **changes: Settings to replace.

        Returns:
            dict: The settings.
        """
        synthetic = {
            'type': 'underlying_peg',
            'watch_instrument_id': INDEX_ID,
            'delta': -0.4,
            'lowest_price': 60,
        }
        synthetic.update(changes)
        return synthetic

    def run(self):
        """Prices the peg, re-anchors it, and prints the refusals.

        Returns:
            None: This method returns nothing.
        """
        runner, intent = self.runner('LIMIT', self.settings())
        runner.run(intent, time.perf_counter())
        quotes = {
            INDEX_ID: {
                'last_price': 25030.00,
            },
        }
        lowest, highest = runner.read_range()
        print(f"Following {runner.underlying()[-2:]}, now at {runner.underlying_price(quotes)}; delta {runner.number('delta', True)}, range {lowest} to {highest}, step {runner.read_step_ticks()} tick")
        view = MarketView(None, runner.tick_size())
        for index_value in (
            25030,
            24900,
            25100,
        ):
            price = runner.target_price(view, decimal.Decimal(index_value), 'SELL')
            print(f'target_price with the index at {index_value}: {price}')
        print(f"bounded(41.23): {runner.bounded(decimal.Decimal('41.23'), view, 'SELL')}, bounded(97.02): {runner.bounded(decimal.Decimal('97.02'), view, 'SELL')}")

        leg = runner.working_leg()
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
            'price': 85.00,
        })
        self.placement.quotes[INDEX_ID] = {
            'last_price': 24990.00,
        }
        runner.on_leg_modified(leg, before)
        print(f"The caller moved the offer to {leg.price} with the index at 24990: start_price {runner.parent.parameters['start_price']}, underlying_start {runner.parent.parameters['underlying_start']}")

        mistakes = [
            (
                'Pegged to itself',
                'LIMIT',
                self.settings(watch_instrument_id=PUT_ID),
                'underlying',
            ),
            (
                'A range upside down',
                'LIMIT',
                self.settings(lowest_price=90, highest_price=70),
                'read_range',
            ),
            (
                'A step of zero ticks',
                'LIMIT',
                self.settings(step_ticks=0),
                'read_step_ticks',
            ),
            (
                'A market order',
                'MARKET',
                self.settings(),
                'run',
            ),
        ]
        for heading, order_type, synthetic, step in mistakes:
            careless, careless_intent = self.runner(order_type, synthetic)
            try:
                if step == 'underlying':
                    careless.underlying()
                elif step == 'read_range':
                    careless.read_range()
                elif step == 'read_step_ticks':
                    careless.read_step_ticks()
                else:
                    careless.run(careless_intent, time.perf_counter())
            except RefusedRequestError as refusal:
                print(f"{heading}: HTTP {refusal.status}, {refusal.body['error']}")


if __name__ == '__main__':
    PricingByHandAndReAnchoringExample().run()
