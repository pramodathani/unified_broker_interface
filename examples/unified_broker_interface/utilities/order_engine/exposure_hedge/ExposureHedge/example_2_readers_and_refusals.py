"""Calls an exposure hedge's readers and its hedge-sending steps by hand, and shows the settings it refuses.

An `ExposureHedge` is built from small steps that this program calls one at a time, on a watch over two bank stocks hedged with a bank index future whose exposure per unit is 30:

- `read_watched`, `read_band` and `read_hedge` read the caller's settings, and `number` reads any one number;
- `remember_tick_size` keeps the hedge instrument's tick size, since the hedge is the only price it works out;
- `held` finds the signed quantity of one instrument in the positions document;
- `exposure` multiplies each watched position by its exposure per unit and adds them up, together with `hedges_in_flight`;
- `hedge_price` prices a hedge two ticks past the touch so that it trades now;
- `send_hedge` sends it and marks the parent `working`.

Last, it shows three refusals, each HTTP 400: a band whose lower edge is not below its upper edge, a hedge instrument whose exposure per unit is zero, and a watched list that is empty.

The placement is a stand-in that serves a positions document, chooses Zerodha and accepts every order; the event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/exposure_hedge/ExposureHedge/example_2_readers_and_refusals.py
"""

import decimal
import logging

from test_runs.engine_stand_ins import (
    RecordingEventLog,
)
from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.exposure_hedge import (
    ExposureHedge,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)

HDFCBANK_ID = '11111111-1111-5111-8111-000000000013'
ICICIBANK_ID = '11111111-1111-5111-8111-000000000016'
BANK_FUTURE_ID = '11111111-1111-5111-8111-000000000017'


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


class ReadersAndRefusalsExample:
    """Calls an exposure hedge's steps by hand, then provokes three refusals.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
    """

    def __init__(self):
        """Builds the stand-in placement with a long in HDFCBANK and a short in ICICIBANK.

        Returns:
            None: This method returns nothing.
        """
        self.placement = StandInPlacement(
            positions={
                'net': [
                    {
                        'instrument_id': HDFCBANK_ID,
                        'product': 'intraday',
                        'quantity': 900,
                    },
                    {
                        'instrument_id': ICICIBANK_ID,
                        'product': 'intraday',
                        'quantity': -200,
                    },
                ],
                'day': [],
            },
        )

    def runner(self, synthetic):
        """An exposure hedge, built but not run.

        Args:
            synthetic (dict): The order type's parameters.

        Returns:
            ExposureHedge: The runner.
        """
        intent = {
            'intent_id': 'intent-1',
            'instrument_id': BANK_FUTURE_ID,
            'body': {
                'instrument_id': BANK_FUTURE_ID,
                'transaction_type': 'SELL',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'price': '56000.00',
                'quantity': 30,
                'synthetic': synthetic,
            },
        }
        runner = ExposureHedge.started(
            intent,
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )
        runner.parent.parameters['tick_size'] = '0.20'
        return runner

    def settings(self, **changes):
        """The watch's settings, with some changed.

        Args:
            **changes: Settings to replace.

        Returns:
            dict: The settings.
        """
        synthetic = {
            'type': 'exposure_hedge',
            'watched': [
                {
                    'instrument_id': HDFCBANK_ID,
                    'exposure_per_unit': 1.1,
                },
                {
                    'instrument_id': ICICIBANK_ID,
                    'exposure_per_unit': 1.2,
                },
            ],
            'lower_band': -300,
            'upper_band': 300,
            'hedge_instrument_id': BANK_FUTURE_ID,
            'hedge_exposure_per_unit': 30,
        }
        synthetic.update(changes)
        return synthetic

    def run(self):
        """Calls the steps and prints the refusals.

        Returns:
            None: This method returns nothing.
        """
        runner = self.runner(self.settings())
        watched = runner.read_watched()
        for instrument_id, per_unit in watched.items():
            print(f'Watching {instrument_id[-2:]} at {per_unit} per unit, holding {runner.held(self.placement.positions, instrument_id)}')
        lower, upper = runner.read_band()
        hedge_instrument, hedge_per_unit = runner.read_hedge()
        print(f'Band: {lower} to {upper}, hedge in {hedge_instrument[-2:]} at {hedge_per_unit} per unit')
        tick_size = runner.remember_tick_size(runner.read_order(runner.parent.body))
        print(f"Tick size kept, the hedge instrument's: {tick_size}")
        print(f"number('12.5'): {runner.number('12.5', 'example')}")
        total = runner.exposure(self.placement.positions)
        print(f'Exposure: {total}, with {runner.hedges_in_flight()} in flight')

        quote = {
            'last_price': 56012.00,
            'depth': {
                'buy': [
                    {
                        'price': 56011.80,
                        'quantity': 90,
                        'orders': 3,
                    },
                ],
                'sell': [
                    {
                        'price': 56012.20,
                        'quantity': 60,
                        'orders': 2,
                    },
                ],
            },
        }
        view = MarketView(quote, decimal.Decimal('0.20'))
        price = runner.hedge_price(view, 'SELL')
        print(f'A sell hedge would go out at {price}')
        runner.send_hedge(BANK_FUTURE_ID, 'SELL', 25, price, total)
        print(f'send_hedge: {self.placement.messages}, parent {runner.parent.state}')
        print(f'Exposure after it: {runner.exposure(self.placement.positions)}')

        mistakes = [
            (
                'A band upside down',
                self.settings(lower_band=300, upper_band=-300),
                'read_band',
            ),
            (
                'A hedge worth nothing',
                self.settings(hedge_exposure_per_unit=0),
                'read_hedge',
            ),
            (
                'Nothing watched',
                self.settings(watched=[]),
                'read_watched',
            ),
        ]
        for heading, synthetic, reader in mistakes:
            careless = self.runner(synthetic)
            try:
                if reader == 'read_band':
                    careless.read_band()
                elif reader == 'read_hedge':
                    careless.read_hedge()
                else:
                    careless.read_watched()
            except RefusedRequestError as refusal:
                print(f"{heading}: HTTP {refusal.status}, {refusal.body['error']}")


if __name__ == '__main__':
    ReadersAndRefusalsExample().run()
