"""Walks through the three steps a square-off takes: find the open positions, cancel the orders resting on them, and build a closing order for each.

A `PositionCloser` works through the order type that owns it, here a real `SquareOff`, so every cancel is recorded on that type's parent. Its three steps are always taken in the same order. First `open_positions` reads the account's net positions on one product. Then `cancel_resting` cancels every open order at every broker on those instruments, because a stop or target left live would fill after the close and open a new position the other way. Finally `closing_order` builds a limit order for each position, priced two ticks past the other side's best price so it fills at once.

The program holds a long intraday position of 50 in one share and a short intraday position of 75 in another, plus a delivery position that the square-off leaves alone. `unified:order-updates` holds two open orders on those instruments, one at Zerodha and one at Dhan, and one completed order that needs no cancel. `resting_orders` lists the open ones, which `cancel_resting` then cancels.

Everything the square-off reads or sends goes through a stand-in placement: `market_context` returns the instrument's broker handles, a quote with depth and the positions document, `cache.hgetall` returns the order updates, and `cancel` accepts every cancel without calling a broker. A stand-in event log keeps the recorded events so the program can print them. Nothing is placed: the closing orders are only built and printed.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/position_closer/PositionCloser/example_1_squaring_off_intraday.py
"""

import json
import logging

from unified_broker_interface.utilities.order_engine.square_off import (
    SquareOff,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.position_closer import (
    PositionCloser,
)

INFY = '11111111-1111-5111-8111-000000000001'
TCS = '11111111-1111-5111-8111-000000000002'
HDFCBANK = '11111111-1111-5111-8111-000000000003'
SYMBOLS = {
    INFY: 'INFY',
    TCS: 'TCS',
    HDFCBANK: 'HDFCBANK',
}


class StandInInstrument:
    """A stand-in for a mapped instrument, holding only its broker handles.

    Attributes:
        handles (dict): Each broker's handle on the instrument, with its tick size.
    """

    def __init__(self, tick_size):
        """Builds an instrument whose three brokers agree on one tick size.

        Args:
            tick_size (str): The tick size in rupees.

        Returns:
            None: This method returns nothing.
        """
        self.handles = {
            'zerodha': {
                'tick_size': tick_size,
            },
            'dhan': {
                'tick_size': tick_size,
            },
            'fyers': {
                'tick_size': tick_size,
            },
        }


class CancelAnswer:
    """A stand-in for a broker's answer to a cancel.

    Attributes:
        outcome (str): `accepted` or `rejected`.
        status_message (str | None): The broker's message.
        response_body (dict): The broker's answer as it sent it.
    """

    def __init__(self, outcome, status_message, response_body):
        """Holds the answer.

        Args:
            outcome (str): `accepted` or `rejected`.
            status_message (str | None): The broker's message.
            response_body (dict): The broker's answer as it sent it.

        Returns:
            None: This method returns nothing.
        """
        self.outcome = outcome
        self.status_message = status_message
        self.response_body = response_body


class OrderUpdatesRedis:
    """A stand-in Redis client holding the order updates hash.

    Attributes:
        updates (dict): Each `broker:order_id` to its latest update as JSON text.
    """

    def __init__(self, updates):
        """Builds the client.

        Args:
            updates (dict): Each `broker:order_id` to its latest update as JSON text.

        Returns:
            None: This method returns nothing.
        """
        self.updates = updates

    def hgetall(self, key):
        """Reads the whole order updates hash.

        Args:
            key (str): The hash, always `unified:order-updates` here.

        Returns:
            dict: Every field and value.
        """
        return dict(self.updates)


class StandInPlacement:
    """A stand-in for the engine's placement, answering from fixed data and accepting every cancel.

    Attributes:
        cache (OrderUpdatesRedis): The stand-in Redis client.
        quotes (dict): Each instrument id to its live quote.
        positions (dict): The unified positions document.
        cancels (list): The cancels sent, as `broker order_id` lines.
    """

    def __init__(self, cache, quotes, positions):
        """Builds the placement.

        Args:
            cache (OrderUpdatesRedis): The stand-in Redis client.
            quotes (dict): Each instrument id to its live quote.
            positions (dict): The unified positions document.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.quotes = quotes
        self.positions = positions
        self.cancels = []

    def market_context(self, instrument_id, needs_quote, needs_positions):
        """Returns the instrument, and the quote and positions when asked for.

        Args:
            instrument_id (str): The instrument.
            needs_quote (bool): Whether to return the quote.
            needs_positions (bool): Whether to return the positions.

        Returns:
            tuple: The instrument (StandInInstrument), the quote (dict | None) and the positions (dict | None).
        """
        quote = None
        if needs_quote:
            quote = self.quotes.get(instrument_id)
        positions = None
        if needs_positions:
            positions = self.positions
        return StandInInstrument('0.05'), quote, positions

    def cancel(self, broker_name, broker_order_id):
        """Accepts a cancel without calling a broker.

        Args:
            broker_name (str): The broker.
            broker_order_id (str): The broker's order id.

        Returns:
            CancelAnswer: An accepted answer.
        """
        self.cancels.append(f'{broker_name} {broker_order_id}')
        response_body = {
            'status': 'success',
            'data': {
                'order_id': broker_order_id,
            },
        }
        return CancelAnswer('accepted', None, response_body)


class ListEventLog:
    """A stand-in for the event log that keeps events in a list.

    Attributes:
        events (list): Every event recorded.
    """

    def __init__(self):
        """Builds an empty log.

        Returns:
            None: This method returns nothing.
        """
        self.events = []

    def record(self, event):
        """Keeps one event.

        Args:
            event (dict): The event.

        Returns:
            None: This method returns nothing.
        """
        self.events.append(event)


class SquaringOffIntradayExample:
    """Finds, cancels and closes the intraday positions of an account, and prints each step.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
        event_log (ListEventLog): The stand-in event log.
        closer (PositionCloser): The closer being shown.
    """

    def __init__(self):
        """Builds a square-off parent over stand-in positions, quotes and order updates.

        Returns:
            None: This method returns nothing.
        """
        positions = {
            'net': [
                {
                    'instrument_id': INFY,
                    'product': 'intraday',
                    'quantity': 50,
                },
                {
                    'instrument_id': TCS,
                    'product': 'intraday',
                    'quantity': -75,
                },
                {
                    'instrument_id': HDFCBANK,
                    'product': 'delivery',
                    'quantity': 20,
                },
            ],
            'day': [],
        }
        quotes = {
            INFY: self.quote(INFY, '1502.40', '1502.50', '1502.45'),
            TCS: self.quote(TCS, '3411.10', '3411.35', '3411.20'),
        }
        updates = {
            'zerodha:250930000123': self.update('zerodha', '250930000123', INFY, 'TRIGGER_PENDING'),
            'dhan:52250930456': self.update('dhan', '52250930456', TCS, 'OPEN'),
            'dhan:52250930400': self.update('dhan', '52250930400', TCS, 'COMPLETE'),
        }
        self.placement = StandInPlacement(OrderUpdatesRedis(updates), quotes, positions)
        self.event_log = ListEventLog()
        parent = ParentOrder('0f5e2c1a-7b3d-4e9f-8a21-6c4d2b1e9f00')
        parent.synthetic_type = 'square_off'
        parent.state = 'working'
        parent.instrument_id = INFY
        parent.body = {
            'instrument_id': INFY,
            'transaction_type': 'SELL',
            'product': 'MIS',
            'order_type': 'MARKET',
            'quantity': 1,
            'synthetic': {
                'type': 'square_off',
            },
        }
        runner = SquareOff(
            parent,
            self.placement,
            self.event_log,
            None,
            logging.getLogger('example'),
        )
        self.closer = PositionCloser(runner)

    def quote(self, instrument_id, best_bid, best_offer, last_price):
        """Builds one live quote with a one-level book.

        Args:
            instrument_id (str): The instrument.
            best_bid (str): The best bid.
            best_offer (str): The best offer.
            last_price (str): The last traded price.

        Returns:
            dict: The quote.
        """
        return {
            'instrument_id': instrument_id,
            'broker': 'zerodha',
            'last_price': float(last_price),
            'stale': False,
            'depth': {
                'buy': [
                    {
                        'price': float(best_bid),
                        'quantity': 400,
                        'orders': 6,
                    },
                ],
                'sell': [
                    {
                        'price': float(best_offer),
                        'quantity': 250,
                        'orders': 4,
                    },
                ],
            },
        }

    def update(self, broker_name, order_id, instrument_id, status):
        """Builds one entry of the order updates hash.

        Args:
            broker_name (str): The broker.
            order_id (str): The broker's order id.
            instrument_id (str): The instrument.
            status (str): The order's status.

        Returns:
            str: The update as JSON text.
        """
        update = {
            'broker': broker_name,
            'order_id': order_id,
            'instrument_id': instrument_id,
            'status': status,
        }
        return json.dumps(update)

    def run(self):
        """Takes the three steps and prints what each found or built.

        Returns:
            None: This method returns nothing.
        """
        positions = self.closer.open_positions('intraday', None)
        for instrument_id, quantity in positions:
            print(f'Open intraday position: {SYMBOLS[instrument_id]} {quantity}')
        instrument_ids = set()
        for instrument_id, _ in positions:
            instrument_ids.add(instrument_id)
        print(f'Resting orders: {sorted(self.closer.resting_orders(instrument_ids))}')
        cancelled = self.closer.cancel_resting(instrument_ids, 'cancelled before squaring off')
        print(f'Cancels accepted: {cancelled}, sent: {sorted(self.placement.cancels)}')
        for event in self.event_log.events:
            print(f'Recorded {event["event"]} for {event["broker"]} {event["broker_order_id"]}: {event.get("outcome")}')
        for instrument_id, quantity in positions:
            order = self.closer.closing_order(instrument_id, quantity)
            print(f'Close {SYMBOLS[instrument_id]}: {order.transaction_type} {order.quantity} {order.product} {order.order_type} at {order.price}')


if __name__ == '__main__':
    SquaringOffIntradayExample().run()
