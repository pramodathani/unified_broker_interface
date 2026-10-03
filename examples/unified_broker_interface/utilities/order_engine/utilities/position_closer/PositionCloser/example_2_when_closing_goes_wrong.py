"""Shows how a position closer behaves when the data it needs is missing or a broker says no.

Closing positions has to keep going when something is wrong, because leaving a position open is usually the worse mistake. This program runs a `PositionCloser`, owned by a real `PlanOrder` running a square-off, through five awkward cases:

1. `open_positions` is asked for only one instrument, so a second open position is left out, and a position of zero is skipped. Positions are read from each broker's own positions hash, so each comes with the broker that holds it.
2. `resting_orders` cannot read Redis the first time. The error is logged and an empty list comes back, so nothing is cancelled and the closing still goes ahead.
3. On the next read Redis answers with one open Zerodha order, and `cancel_resting` sends a cancel that the broker refuses. The refusal is recorded on the parent and counted as not accepted, and the closing carries on.
4. `closing_order` finds an empty book, so it prices two ticks past the last traded price instead of past the best bid.
5. `closing_order` finds no quote at all, or brokers that disagree on the tick size, and returns None rather than guess a price.

A stand-in placement answers every read from fixed data, serving Zerodha's positions hash and the token lookup from the positions the program holds, raises `redis.ConnectionError` the first time the order updates are read, and refuses every cancel with the `RefusedRequestError` a broker class raises for an order that is already complete. A stand-in event log keeps the recorded events, and a stand-in logger keeps the error message. The program needs no broker, no data store and no network, and places nothing.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/position_closer/PositionCloser/example_2_when_closing_goes_wrong.py
"""

import json

import redis

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.plan import (
    PlanOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.position_closer import (
    PositionCloser,
)

SBIN = '22222222-2222-5222-8222-000000000001'
ITC = '22222222-2222-5222-8222-000000000002'
WIPRO = '22222222-2222-5222-8222-000000000003'
UNQUOTED = '22222222-2222-5222-8222-000000000004'
DISPUTED = '22222222-2222-5222-8222-000000000005'


class StandInInstrument:
    """A stand-in for a mapped instrument, holding only its broker handles.

    Attributes:
        handles (dict): Each broker's handle on the instrument, with its tick size.
    """

    def __init__(self, handles):
        """Builds the instrument.

        Args:
            handles (dict): Each broker's handle on the instrument.

        Returns:
            None: This method returns nothing.
        """
        self.handles = handles


class FlakyRedis:
    """A stand-in Redis client that cannot be reached on the first read and answers on every later one.

    Attributes:
        reads (int): How many reads have been asked for.
        updates (dict): Each `broker:order_id` to its latest update as JSON text.
    """

    def __init__(self, updates):
        """Builds the client.

        Args:
            updates (dict): Each `broker:order_id` to its latest update as JSON text.

        Returns:
            None: This method returns nothing.
        """
        self.reads = 0
        self.updates = updates

    def hgetall(self, key):
        """Reads the whole order updates hash, failing the first time as a real client does when the server is down.

        Args:
            key (str): The hash, always `unified:order-updates` here.

        Returns:
            dict: Every field and value.

        Raises:
            redis.ConnectionError: On the first read.
        """
        self.reads = self.reads + 1
        if self.reads == 1:
            raise redis.ConnectionError('Error 111 connecting to localhost:6379. Connection refused.')
        return dict(self.updates)


class BrokerPositionsRedis:
    """Stands in for Redis as the position closer reads it: the order updates from another stand-in, and Zerodha's own positions and the token lookup, made from the positions document.

    The position closer reads each broker's `<broker>:portfolio:positions` hash rather than the unified positions document, because a closing order has to go to the broker that holds the position, and it finds each position's instrument from the broker's token in `unified:broker_tokens`. Here every position is held at Zerodha, and an instrument's token is its own id.

    Attributes:
        inner (object): The stand-in that holds the order updates.
        positions (dict | None): The unified positions document the program set up.
    """

    PRODUCT_CODES = {
        'intraday': 'MIS',
        'delivery': 'CNC',
        'carry': 'NRML',
        'carryforward': 'NRML',
    }

    def __init__(self, inner, positions):
        """Builds the stand-in.

        Args:
            inner (object): The stand-in that holds the order updates.
            positions (dict | None): The unified positions document.

        Returns:
            None: This method returns nothing.
        """
        self.inner = inner
        self.positions = positions

    def hgetall(self, key):
        """Reads a whole hash: Zerodha's positions, or whatever the inner stand-in holds.

        Args:
            key (str): The key.

        Returns:
            dict: The hash's fields and values.
        """
        if key != 'zerodha:portfolio:positions':
            return self.inner.hgetall(key)
        entries = {}
        for row in (self.positions or {}).get('net') or []:
            code = self.PRODUCT_CODES.get(row['product'], row['product'].upper())
            entries[f"NET:{row['instrument_id']}:{code}"] = json.dumps({
                'position': {
                    'instrument_token': row['instrument_id'],
                    'product': code,
                    'quantity': row['quantity'],
                    'day_or_net': 'NET',
                },
            })
        return entries

    def hget(self, key, field):
        """Reads one field, which is only ever a token in `unified:broker_tokens`.

        Args:
            key (str): The key.
            field (str): `broker:token`.

        Returns:
            str | None: The instruments the token names, as JSON, or None.
        """
        if key != 'unified:broker_tokens' or not field.startswith('zerodha:'):
            return None
        return json.dumps([
            field.split(':', 1)[1],
        ])

    def pipeline(self, transaction=True):
        """A pipeline that answers each queued read from this stand-in.

        Args:
            transaction (bool): Unused.

        Returns:
            StandInPipeline: The pipeline.
        """
        del transaction
        return StandInPipeline(self)


class StandInPipeline:
    """Stands in for a Redis pipeline, queueing reads and answering them all at once.

    Attributes:
        redis (BrokerPositionsRedis): The stand-in the reads are answered from.
        keys (list): The hashes queued, in order.
    """

    def __init__(self, redis):
        """Builds an empty pipeline.

        Args:
            redis (BrokerPositionsRedis): The stand-in the reads are answered from.

        Returns:
            None: This method returns nothing.
        """
        self.redis = redis
        self.keys = []

    def hgetall(self, key):
        """Queues reading a whole hash.

        Args:
            key (str): The key.

        Returns:
            None: This method returns nothing.
        """
        self.keys.append(key)

    def execute(self):
        """Answers every queued read.

        Returns:
            list: One hash per queued read, in order.
        """
        answers = []
        for key in self.keys:
            answers.append(self.redis.hgetall(key))
        return answers


class StandInOrderPlacement:
    """Stands in for the order placement, which names the brokers the system trades with.

    Attributes:
        broker_names (list): The brokers, which here is only Zerodha.
    """

    def __init__(self):
        """Builds the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.broker_names = [
            'zerodha',
        ]


class StandInPlacement:
    """A stand-in for the engine's placement that answers from fixed data and refuses every cancel.

    Attributes:
        cache (BrokerPositionsRedis): The stand-in Redis client, whose order updates come from a `FlakyRedis`.
        quotes (dict): Each instrument id to its live quote.
        positions (dict): The unified positions document.
        order_placement (StandInOrderPlacement): Names the brokers the system trades with.
    """

    def __init__(self, quotes, positions):
        """Builds the placement.

        Args:
            quotes (dict): Each instrument id to its live quote.
            positions (dict): The unified positions document.

        Returns:
            None: This method returns nothing.
        """
        open_order = {
            'broker': 'zerodha',
            'order_id': '250930000777',
            'instrument_id': SBIN,
            'status': 'OPEN',
        }
        updates = {
            'zerodha:250930000777': json.dumps(open_order),
        }
        self.cache = BrokerPositionsRedis(FlakyRedis(updates), positions)
        self.quotes = quotes
        self.positions = positions
        self.order_placement = StandInOrderPlacement()

    def market_context(self, instrument_id, needs_quote, needs_positions):
        """Returns the instrument, and the quote and positions when asked for.

        The instrument `DISPUTED` has two brokers that disagree on its tick size.

        Args:
            instrument_id (str): The instrument.
            needs_quote (bool): Whether to return the quote.
            needs_positions (bool): Whether to return the positions.

        Returns:
            tuple: The instrument (StandInInstrument), the quote (dict | None) and the positions (dict | None).
        """
        handles = {
            'zerodha': {
                'tick_size': '0.05',
            },
            'dhan': {
                'tick_size': '0.05',
            },
        }
        if instrument_id == DISPUTED:
            handles['dhan'] = {
                'tick_size': '0.10',
            }
        quote = None
        if needs_quote:
            quote = self.quotes.get(instrument_id)
        positions = None
        if needs_positions:
            positions = self.positions
        return StandInInstrument(handles), quote, positions

    def cancel(self, broker_name, broker_order_id):
        """Refuses the cancel, as a broker does for an order that has already completed.

        Args:
            broker_name (str): The broker.
            broker_order_id (str): The broker's order id.

        Returns:
            CancelAnswer: Never returns.

        Raises:
            RefusedRequestError: Always.
        """
        raise RefusedRequestError.refusal(
            f'{broker_name} refused the cancel: the order {broker_order_id} is already complete',
            409,
            broker=broker_name,
        )


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


class RecordingLogger:
    """A stand-in logger that keeps every message instead of writing it.

    Attributes:
        messages (list): The messages received, each prefixed with its level.
    """

    def __init__(self):
        """Builds the logger with no messages.

        Returns:
            None: This method returns nothing.
        """
        self.messages = []

    def error(self, message):
        """Keeps an error message.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        self.messages.append(f'ERROR {message}')


class WhenClosingGoesWrongExample:
    """Runs a closer through five awkward cases and prints what it did in each.

    Attributes:
        event_log (ListEventLog): The stand-in event log.
        logger (RecordingLogger): The stand-in logger.
        closer (PositionCloser): The closer being shown.
    """

    def __init__(self):
        """Builds a square-off parent over stand-in positions and quotes.

        Returns:
            None: This method returns nothing.
        """
        positions = {
            'net': [
                {
                    'instrument_id': SBIN,
                    'product': 'intraday',
                    'quantity': 300,
                },
                {
                    'instrument_id': ITC,
                    'product': 'intraday',
                    'quantity': -500,
                },
                {
                    'instrument_id': WIPRO,
                    'product': 'intraday',
                    'quantity': 0,
                },
            ],
            'day': [],
        }
        empty_book_quote = {
            'instrument_id': SBIN,
            'last_price': 812.35,
            'stale': False,
            'depth': {
                'buy': [],
                'sell': [],
            },
        }
        disputed_quote = {
            'instrument_id': DISPUTED,
            'last_price': 101.5,
            'stale': False,
        }
        quotes = {
            SBIN: empty_book_quote,
            DISPUTED: disputed_quote,
        }
        self.event_log = ListEventLog()
        self.logger = RecordingLogger()
        parent = ParentOrder('5a1c9e20-3d4b-4f6a-9b8c-7e2d1f0a3b4c')
        parent.synthetic_type = 'plan'
        parent.state = 'working'
        parent.instrument_id = SBIN
        parent.body = {
            'instrument_id': SBIN,
            'transaction_type': 'SELL',
            'product': 'MIS',
            'order_type': 'MARKET',
            'quantity': 1,
        }
        runner = PlanOrder(
            parent,
            StandInPlacement(quotes, positions),
            self.event_log,
            None,
            self.logger,
        )
        self.closer = PositionCloser(runner)

    def run(self):
        """Runs the five cases and prints the results.

        Returns:
            None: This method returns nothing.
        """
        wanted = {
            SBIN,
            WIPRO,
        }
        positions = self.closer.open_positions('intraday', wanted)
        for broker_name, instrument_id, quantity in positions:
            print(f'1. Open intraday position in SBIN or WIPRO: {instrument_id} {quantity} at {broker_name}')
        watched = {
            SBIN,
        }
        print(f'2. Resting orders with Redis down: {self.closer.resting_orders(watched)}')
        accepted = self.closer.cancel_resting(watched, 'cancelled before squaring off')
        print(f'3. Cancels accepted once Redis answers: {accepted}')
        for event in self.event_log.events:
            print(f'   Recorded {event["event"]} for {event["broker"]} {event["broker_order_id"]}: {event.get("outcome")}, {event.get("status_message")}')
        order = self.closer.closing_order(SBIN, 300)
        print(f'4. Close SBIN with an empty book: {order.transaction_type} {order.quantity} {order.order_type} at {order.price}')
        print(f'5. Close with no quote: {self.closer.closing_order(UNQUOTED, 10)}')
        print(f'   Close with disputed tick sizes: {self.closer.closing_order(DISPUTED, 10)}')
        for message in self.logger.messages:
            print(message)


if __name__ == '__main__':
    WhenClosingGoesWrongExample().run()
