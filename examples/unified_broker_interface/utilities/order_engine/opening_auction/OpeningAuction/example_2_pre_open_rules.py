"""Walks through the pre-open's rules as an opening-auction order applies them: which instruments and orders it takes, and until when.

`OpeningAuction.read_place_at` decides when an auction order is placed, and `collection_closes` when the pre-open stops taking it. This program asks both on Thursday 1 October 2026 with the engine's clock stopped at different moments, and prints what each gives or the HTTP 400 refusal:

1. A RELIANCE limit buy asked at 09:02, while collection is already open, is placed at once.
2. A Nifty future limit buy is taken until 09:07, when NSE's futures pre-open may close at any moment.
3. A Nifty option has no pre-open at all and is refused.
4. A stop-loss order and an IOC order are refused, because the pre-open takes neither.
5. A RELIANCE limit buy asked at 09:12, after collection has closed, is refused rather than sent into continuous trading, and the refusal names the next auction's date.
6. An `at_time` of 09:12, after collection closes, is refused as well.

`read_place_at` reads the time from the engine's `Moments` clock, so the program replaces that clock, in the `opening_auction` module, with a stand-in whose moment it sets before each question. The placement is a stand-in that knows each instrument's segment; nothing is sent in this program. The event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine. The trading calendar is read from the calendar files kept in the repository.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/opening_auction/OpeningAuction/example_2_pre_open_rules.py
"""

import datetime
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
from unified_broker_interface.utilities.order_engine import opening_auction
from unified_broker_interface.utilities.order_engine.opening_auction import (
    OpeningAuction,
)
from unified_broker_interface.utilities.order_engine.utilities.moments import (
    INDIA,
    Moments,
)

RELIANCE = '11111111-1111-5111-8111-000000000001'
NIFTY_FUTURE = '11111111-1111-5111-8111-000000000009'
NIFTY_OPTION = '11111111-1111-5111-8111-000000000003'


class StoppedMoments(Moments):
    """The engine's clock, stopped at whatever moment the program sets.

    Attributes:
        MOMENT (datetime.datetime): The moment every instance answers with.
    """

    MOMENT = datetime.datetime(2026, 10, 1, 9, 2, tzinfo=INDIA)

    def now(self):
        """The stopped moment.

        Returns:
            datetime.datetime: The moment set on the class.
        """
        return StoppedMoments.MOMENT


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


class PreOpenRulesExample:
    """Asks an opening-auction order when it would be placed, under different rules.

    Attributes:
        placement (StandInPlacement): The stand-in placement, which knows each instrument's segment.
    """

    def __init__(self):
        """Stops the clock and describes the three instruments.

        Returns:
            None: This method returns nothing.
        """
        opening_auction.Moments = StoppedMoments
        self.placement = StandInPlacement()
        self.placement.identities[NIFTY_FUTURE] = {
            'segment': 'nse_equity_index_futures',
        }
        self.placement.identities[NIFTY_OPTION] = {
            'segment': 'nse_equity_index_options',
        }

    def ask(self, heading, moment, instrument_id, changes, synthetic=None):
        """Asks when one order would be placed and prints the answer or the refusal.

        Args:
            heading (str): What is being asked.
            moment (datetime.time): The time on Thursday 1 October the clock is stopped at.
            instrument_id (str): The instrument.
            changes (dict): Body fields that differ from a plain limit buy.
            synthetic (dict | None): The order type's parameters, or None for the defaults.

        Returns:
            None: This method returns nothing.
        """
        StoppedMoments.MOMENT = datetime.datetime.combine(
            datetime.date(2026, 10, 1),
            moment,
            INDIA,
        )
        body = {
            'instrument_id': instrument_id,
            'transaction_type': 'BUY',
            'product': 'NRML',
            'order_type': 'LIMIT',
            'price': '1380.00',
            'quantity': 75,
            'synthetic': synthetic or {
                'type': 'opening_auction',
            },
        }
        body.update(changes)
        runner = OpeningAuction.started(
            {
                'intent_id': 'intent-1',
                'instrument_id': instrument_id,
                'body': body,
            },
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )
        order = runner.read_order(runner.parent.body)
        try:
            closes = runner.collection_closes(order)
            _, place_at_text = runner.read_place_at(order)
        except RefusedRequestError as refusal:
            print(f"{heading}: HTTP {refusal.status}, {refusal.body['error']}")
            return
        print(f'{heading}: taken until {closes}, placed at {place_at_text}')

    def run(self):
        """Asks the six questions.

        Returns:
            None: This method returns nothing.
        """
        self.ask('RELIANCE at 09:02', datetime.time(9, 2), RELIANCE, {})
        self.ask('Nifty future at 08:30', datetime.time(8, 30), NIFTY_FUTURE, {})
        self.ask('Nifty option at 08:30', datetime.time(8, 30), NIFTY_OPTION, {})
        self.ask(
            'A stop-loss order',
            datetime.time(8, 30),
            RELIANCE,
            {
                'order_type': 'SL',
                'trigger_price': '1379.00',
            },
        )
        self.ask(
            'An IOC order',
            datetime.time(8, 30),
            RELIANCE,
            {
                'validity': 'IOC',
            },
        )
        self.ask('RELIANCE at 09:12', datetime.time(9, 12), RELIANCE, {})
        self.ask(
            'at_time 09:12',
            datetime.time(8, 30),
            RELIANCE,
            {},
            {
                'type': 'opening_auction',
                'at_time': '09:12',
            },
        )


if __name__ == '__main__':
    PreOpenRulesExample().run()
