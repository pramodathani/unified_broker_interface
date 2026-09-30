"""Sizes an option's hedge by its delta, and shows the sizing mistakes an attached hedge refuses.

With `delta_volatility` in place of `ratio`, an `AttachedHedge` must be trading an option. `option_details` reads the option's strike, expiry and kind from the instrument's identity, and at each fill `hedge_ratio` works out the Black-76 delta at that volatility, with the hedge future's last price as the forward.

This program buys two lots of a deep in-the-money Nifty call, strike 10,000 against a future at 24,000 and expiring on 24 September 2030, and hedges it in the future. So deep in the money its delta rounds to 1.00 whatever day the program is run, which keeps the output the same; that is why such an option was chosen. When both lots fill, 150 units of delta need hedging, so two lots of 75 futures are sold. The printed delta is rounded to two places for the same reason.

It then shows three refusals from `check_sizing` and `hedge_instrument`: both `ratio` and `delta_volatility` given, delta sizing asked for on a stock, and a hedge in the entry's own instrument.

The placement is a stand-in that serves fixed identities, quotes and lot sizes, chooses Zerodha and accepts every order; the event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine. The fill is recorded as a `leg_update` event through the runner and handed to `on_leg_update`, as the engine's order update follower does.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/attached_hedge/AttachedHedge/example_2_delta_hedge_and_refusals.py
"""

import datetime
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
from unified_broker_interface.utilities.order_engine.attached_hedge import (
    AttachedHedge,
)

OPTION_ID = '11111111-1111-5111-8111-000000000003'
FUTURE_ID = '11111111-1111-5111-8111-000000000009'
STOCK_ID = '11111111-1111-5111-8111-000000000001'


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


class DeltaHedgeAndRefusalsExample:
    """Delta-hedges a filled call, then provokes three refusals.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
    """

    def __init__(self):
        """Builds the stand-in placement with the option, the future and a stock.

        Returns:
            None: This method returns nothing.
        """
        self.placement = StandInPlacement(
            quotes={
                FUTURE_ID: {
                    'last_price': 24000.00,
                    'depth': {
                        'buy': [
                            {
                                'price': 23999.50,
                                'quantity': 300,
                                'orders': 2,
                            },
                        ],
                        'sell': [
                            {
                                'price': 24000.50,
                                'quantity': 300,
                                'orders': 2,
                            },
                        ],
                    },
                },
            },
        )
        self.placement.identities[OPTION_ID] = {
            'segment': 'nse_equity_index_options',
            'option_type': 'CE',
            'strike_price': 10000,
            'expiry_date': '2030-09-24',
        }
        self.placement.identities[FUTURE_ID] = {
            'segment': 'nse_equity_index_futures',
        }
        self.placement.lot_sizes[OPTION_ID] = 75
        self.placement.lot_sizes[FUTURE_ID] = 75

    def runner(self, instrument_id, synthetic):
        """A runner for a buy of 150 units of an instrument, built but not run.

        Args:
            instrument_id (str): The instrument bought.
            synthetic (dict): The order type's parameters.

        Returns:
            AttachedHedge: The runner.
        """
        return AttachedHedge.started(
            self.intent(instrument_id, synthetic),
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )

    def intent(self, instrument_id, synthetic):
        """An intent buying 150 units of an instrument at 14,000.

        Args:
            instrument_id (str): The instrument bought.
            synthetic (dict): The order type's parameters.

        Returns:
            dict: The intent.
        """
        return {
            'intent_id': 'intent-1',
            'instrument_id': instrument_id,
            'body': {
                'instrument_id': instrument_id,
                'transaction_type': 'BUY',
                'product': 'NRML',
                'order_type': 'LIMIT',
                'price': '14000.00',
                'quantity': 150,
                'synthetic': synthetic,
            },
        }

    def run(self):
        """Hedges one filled call by its delta and prints three refusals.

        Returns:
            None: This method returns nothing.
        """
        synthetic = {
            'type': 'attached_hedge',
            'hedge_instrument_id': FUTURE_ID,
            'delta_volatility': 15,
        }
        runner = self.runner(OPTION_ID, synthetic)
        runner.check_sizing()
        strike, expires_at, is_call = runner.option_details()
        expires = datetime.datetime.fromtimestamp(expires_at, datetime.timezone.utc)
        print(f'Option: strike {strike}, call {is_call}, expires {expires.isoformat()}')
        body, status = runner.run(self.intent(OPTION_ID, synthetic), time.perf_counter())
        print(f"Run: HTTP {status}, outcome {body['outcome']}")
        print(f'Delta at 15 per cent volatility: {round(runner.hedge_ratio(), 2)}')
        entry = runner.parent.legs[0]
        changes = {
            'leg_state': 'filled',
            'filled_quantity': 150,
        }
        runner.record({
            'event': 'leg_update',
            'parent_state': runner.parent.state,
            'leg_id': entry.leg_id,
            'leg_role': entry.role,
            'leg_state': 'filled',
            'filled_quantity': 150,
        })
        runner.on_leg_update(entry, changes)
        print(f'Sent to the broker: {self.placement.messages}')
        print(f'Parent: {runner.parent.state}')

        both = self.runner(OPTION_ID, {
            'type': 'attached_hedge',
            'hedge_instrument_id': FUTURE_ID,
            'ratio': 1,
            'delta_volatility': 15,
        })
        try:
            both.check_sizing()
        except RefusedRequestError as refusal:
            print(f"Both sizings: HTTP {refusal.status}, {refusal.body['error']}")

        stock = self.runner(STOCK_ID, synthetic)
        try:
            stock.check_sizing()
        except RefusedRequestError as refusal:
            print(f"Delta on a stock: HTTP {refusal.status}, {refusal.body['error']}")

        itself = self.runner(FUTURE_ID, synthetic)
        try:
            itself.hedge_instrument()
        except RefusedRequestError as refusal:
            print(f"Hedged in itself: HTTP {refusal.status}, {refusal.body['error']}")


if __name__ == '__main__':
    DeltaHedgeAndRefusalsExample().run()
