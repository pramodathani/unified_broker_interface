"""Shows a daily stop's decisions by hand: the first morning it arms, a morning that gaps through the stop, and the day it expires.

A `DailyStop` makes three decisions that this program calls directly, on a short of 30 TCS protected by a buy stop triggering at 3,950 with a limit of 3,960:

- `first_arming_day` says which morning the stop is first placed: today when it trades and 09:20 has not passed, otherwise the next trading day;
- `gapped_through` says whether the market has already passed the stop's level, and `exit_side` which side closes the position;
- when it has, `exit_now` closes the position with a limit two ticks past the touch instead of placing a stop that would be refused or fire at once, and the parent ends as `completed`; when it has not, `arm_stop` places the stop.

Last, a tick at or after `expires_at` ends the parent as `completed`, because a stop still being placed for a position closed weeks ago is worse than no stop. `read_valid_days` shows the number of days, and a stop with only one of its two prices is refused by `read_stop_prices`.

The placement is a stand-in that chooses Zerodha and accepts every order; the event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine. Every moment is fixed, and the trading calendar is read from the calendar files kept in the repository.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/daily_stop/DailyStop/example_2_gap_through_and_expiry.py
"""

import datetime
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
from unified_broker_interface.utilities.order_engine.daily_stop import (
    DailyStop,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.moments import (
    INDIA,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000010'


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


class GapThroughAndExpiryExample:
    """Calls a daily stop's decisions by hand and prints each answer."""

    def runner(self, synthetic):
        """A daily stop over a short of 30 TCS, built but not run.

        Args:
            synthetic (dict): The order type's parameters.

        Returns:
            DailyStop: The runner.
        """
        intent = {
            'intent_id': 'intent-1',
            'instrument_id': INSTRUMENT_ID,
            'body': {
                'instrument_id': INSTRUMENT_ID,
                'transaction_type': 'SELL',
                'product': 'NRML',
                'order_type': 'LIMIT',
                'price': 3900,
                'quantity': 30,
                'synthetic': synthetic,
            },
        }
        runner = DailyStop.started(
            intent,
            StandInPlacement(),
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )
        runner.parent.parameters['tick_size'] = '0.05'
        return runner

    def run(self):
        """Prints the decisions and the two endings.

        Returns:
            None: This method returns nothing.
        """
        synthetic = {
            'type': 'daily_stop',
            'stop_price': 3950,
            'stop_limit_price': 3960,
            'valid_days': 5,
        }
        runner = self.runner(synthetic)
        print(f'Valid for {runner.read_valid_days()} days')
        moments = [
            datetime.datetime(2026, 10, 1, 8, 0, tzinfo=INDIA),
            datetime.datetime(2026, 10, 1, 14, 0, tzinfo=INDIA),
            datetime.datetime(2026, 10, 3, 12, 0, tzinfo=INDIA),
        ]
        for moment in moments:
            first = runner.first_arming_day(moment.timestamp(), 'nse_equities')
            print(f'Recorded {moment:%a %d %b %H:%M}: first placed on {first:%a %d %b}')

        order = runner.read_order(runner.parent.body)
        side = runner.exit_side(order.transaction_type)
        trigger, limit = runner.read_stop_prices()
        for last in (
            decimal.Decimal('3921.50'),
            decimal.Decimal('3987.00'),
        ):
            print(f'Last {last}: the {side} stop at {trigger} has been gapped through: {runner.gapped_through(last, trigger, side)}')

        quote = {
            'last_price': 3987.00,
            'depth': {
                'buy': [
                    {
                        'price': 3986.50,
                        'quantity': 40,
                        'orders': 2,
                    },
                ],
                'sell': [
                    {
                        'price': 3987.50,
                        'quantity': 40,
                        'orders': 2,
                    },
                ],
            },
        }
        view = MarketView(quote, decimal.Decimal('0.05'))
        runner.exit_now(order, side, view, decimal.Decimal('3987.00'), trigger)
        print(f'exit_now: sent {runner.placement.messages}, parent {runner.parent.state}')
        print(f'  {runner.parent.last_error}')

        calm = self.runner(synthetic)
        calm.arm_stop(order, side, trigger, limit)
        print(f'arm_stop: sent {calm.placement.messages}, parent {calm.parent.state}')
        expires_at = datetime.datetime(2026, 10, 6, 18, 0, tzinfo=INDIA).timestamp()
        calm.parent.parameters['expires_at'] = expires_at
        ended = calm.on_clock_tick(expires_at + 60)
        print(f'Tick after expiry: acted {ended}, parent {calm.parent.state}, {calm.parent.last_error}')

        half = self.runner({
            'type': 'daily_stop',
            'stop_price': 3950,
        })
        try:
            half.read_stop_prices()
        except RefusedRequestError as refusal:
            print(f"Only stop_price: HTTP {refusal.status}, {refusal.body['error']}")


if __name__ == '__main__':
    GapThroughAndExpiryExample().run()
