"""Hands each parent's quotes to the worker that owns it, skips a parent whose last price tick is still waiting, and survives Redis being unreachable.

In the running engine a `PriceTicker` is given the engine's `ParentRouter`. On each `tick` it reads the quotes once and then, instead of running the parent itself, calls `hand_over`, which routes the parent and its quotes to the worker that owns it. The worker calls `run_handed_over`, which reads the parent afresh and gives it the quotes. While that is still waiting, the next tick does not queue a second piece of work for the same parent, so a worker stuck on a slow broker call never works through a pile of stale quotes.

This program shows that with a real router for Dhan. The owning worker is first given a piece of work that waits on a `threading.Event`, standing in for a slow broker call, so the first tick's work is certainly still pending when the program ticks again. The program then releases the worker and waits until every worker is idle, so the output does not depend on thread timing. It also calls `run_handed_over` and `run_one` directly, and finally swaps in a stand-in Redis client that raises `redis.ConnectionError`, which the ticker logs and treats as no quotes at all.

A small order type of the program's own, `example_quote_counter`, is added to the registry so the output does not depend on the time of day; it records the last price it was given and acts. The parent record lives in a small stand-in parent store, a stand-in logger keeps the error message, and the program needs no broker, no data store and no network.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/price_ticker/PriceTicker/example_2_quotes_handed_to_workers.py
"""

import json
import threading

import redis

from unified_broker_interface.utilities.order_engine.base import (
    SyntheticOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_router import (
    ParentRouter,
)
from unified_broker_interface.utilities.order_engine.utilities.price_ticker import (
    PriceTicker,
)
from unified_broker_interface.utilities.order_engine.utilities.registry import (
    SYNTHETIC_ORDER_CLASSES,
)

CRUDE_FUTURE = 'mcx-crudeoil-2026-10-19-future'


class QuoteCounter(SyntheticOrder):
    """A small order type that records every quote it is given, for this program only.

    Attributes:
        SYNTHETIC_TYPE (str): The name the registry knows it by.
        WANTS_PRICES (bool): True, so the ticker gives it quotes.
        SEEN (list): What each price tick saw, on whichever thread ran it.
    """

    SYNTHETIC_TYPE = 'example_quote_counter'
    WANTS_PRICES = True
    SEEN = []

    def on_price_tick(self, quotes, now):
        """Records the last price of its own instrument and acts.

        Args:
            quotes (dict): The quote for each instrument the parent watches.
            now (float): The time of the tick, in seconds since the epoch.

        Returns:
            bool: Always True.
        """
        quote = quotes.get(self.parent.instrument_id)
        QuoteCounter.SEEN.append(f'{self.parent.parent_order_id} saw {quote["last_price"]} on {threading.current_thread().name}')
        return True


class QuotesRedis:
    """A stand-in Redis client holding the live quotes hash.

    Attributes:
        quotes (dict): Each instrument id to its quote text.
    """

    def __init__(self, quotes):
        """Builds the client.

        Args:
            quotes (dict): Each instrument id to its quote text.

        Returns:
            None: This method returns nothing.
        """
        self.quotes = quotes

    def hmget(self, key, fields):
        """Reads several fields of the quotes hash.

        Args:
            key (str): The hash, always `unified:quotes:live` here.
            fields (list): The fields.

        Returns:
            list: Each field's value, or None where it is missing.
        """
        values = []
        for field in fields:
            values.append(self.quotes.get(field))
        return values


class UnreachableRedis:
    """A stand-in Redis client whose server cannot be reached."""

    def hmget(self, key, fields):
        """Fails as a real client does when the server is down.

        Args:
            key (str): The hash.
            fields (list): The fields.

        Returns:
            list: Never returns.

        Raises:
            redis.ConnectionError: Always.
        """
        raise redis.ConnectionError('Error 111 connecting to localhost:6379. Connection refused.')


class DictionaryParentStore:
    """A stand-in for the parent store that keeps parent records in a dictionary.

    Attributes:
        documents (dict): Each parent order id to its record.
    """

    def __init__(self, documents):
        """Builds the store.

        Args:
            documents (dict): Each parent order id to its record.

        Returns:
            None: This method returns nothing.
        """
        self.documents = documents

    def open_parent_ids(self):
        """The ids of the open parents.

        Returns:
            list: The ids, sorted.
        """
        return sorted(self.documents)

    def parent(self, parent_order_id):
        """One parent's record.

        Args:
            parent_order_id (str): The parent's id.

        Returns:
            dict | None: The record, or None when there is none.
        """
        return self.documents.get(parent_order_id)


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

    def info(self, message):
        """Keeps an information message.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        self.messages.append(f'INFO {message}')

    def error(self, message):
        """Keeps an error message.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        self.messages.append(f'ERROR {message}')

    def exception(self, message):
        """Keeps an error message written while handling an exception.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        self.messages.append(f'EXCEPTION {message}')


class QuotesHandedToWorkersExample:
    """Ticks one parent twice through a router while its worker is busy, then ticks with Redis down.

    Attributes:
        document (dict): The one parent's record.
        logger (RecordingLogger): The stand-in logger.
        router (ParentRouter): The router that owns the worker threads.
        ticker (PriceTicker): The ticker being shown.
        release (threading.Event): Set to let the slow piece of work finish.
        started (threading.Event): Set once the slow piece of work is running.
    """

    def __init__(self):
        """Adds the example type to the registry and builds a router and a ticker over one Dhan parent.

        Returns:
            None: This method returns nothing.
        """
        SYNTHETIC_ORDER_CLASSES[QuoteCounter.SYNTHETIC_TYPE] = QuoteCounter
        self.document = {
            'parent_order_id': 'parent-1',
            'synthetic_type': 'example_quote_counter',
            'state': 'working',
            'instrument_id': CRUDE_FUTURE,
            'parameters': {},
            'legs': [
                {
                    'leg_id': 'leg-1',
                    'broker': 'dhan',
                    'instrument_id': CRUDE_FUTURE,
                },
            ],
        }
        documents = {
            'parent-1': self.document,
        }
        quote = {
            'instrument_id': CRUDE_FUTURE,
            'broker': 'dhan',
            'symbol': 'CRUDEOIL',
            'last_price': 5873.0,
            'stale': False,
        }
        quotes = {
            CRUDE_FUTURE: json.dumps(quote),
        }
        broker_names = [
            'dhan',
        ]
        self.logger = RecordingLogger()
        self.router = ParentRouter(broker_names, {}, 1, self.logger)
        self.ticker = PriceTicker(
            QuotesRedis(quotes),
            DictionaryParentStore(documents),
            None,
            None,
            self.logger,
            None,
            self.router,
        )
        self.release = threading.Event()
        self.started = threading.Event()

    def slow_broker_call(self):
        """Pretends to wait for a slow broker until the program releases it.

        Returns:
            None: This method returns nothing.
        """
        self.started.set()
        self.release.wait(5.0)

    def run(self):
        """Ticks while the worker is busy, releases it, ticks with Redis down and prints the results.

        Returns:
            None: This method returns nothing.
        """
        self.router.start()
        self.router.route('parent-1', 'dhan', self.slow_broker_call, ())
        self.started.wait(5.0)
        self.ticker.tick()
        print(f'Pending after the first tick: {sorted(self.ticker.pending)}')
        self.ticker.tick()
        quotes = {
            CRUDE_FUTURE: None,
        }
        self.ticker.hand_over(self.document, quotes)
        print(f'Work waiting on the worker after two more tries: {self.router.total_load()}')
        self.release.set()
        self.router.wait_until_idle(threading.Event(), 5.0)
        print(f'Pending once the worker is free: {sorted(self.ticker.pending)}')
        print(f'Ticks: {self.ticker.ticks}, acted in total: {self.ticker.acted}')
        own_quotes = self.ticker.quotes([
            CRUDE_FUTURE,
        ])
        self.ticker.run_handed_over('parent-1', own_quotes)
        print(f'Acted in total after running a handed-over tick here: {self.ticker.acted}')
        print(f'run_one acts: {self.ticker.run_one(dict(self.document), own_quotes)}')
        self.ticker.cache = UnreachableRedis()
        unreachable_quotes = self.ticker.quotes([
            CRUDE_FUTURE,
        ])
        print(f'Quotes with Redis down: {unreachable_quotes}')
        for line in QuoteCounter.SEEN:
            print(line)
        for message in self.logger.messages:
            print(message)
        print(f'Every worker stopped: {self.router.stop(5.0)}')


if __name__ == '__main__':
    QuotesHandedToWorkersExample().run()
