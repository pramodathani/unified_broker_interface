"""Runs the synthetic limit order book's main loop through a Redis outage and shows it rebasing every estimate when Redis comes back.

`VirtualBook.run` is the loop the `bin/unified/orders/virtual_book` script runs: one pass after another until its stop event is set. When Redis cannot be reached it logs the error, waits with a doubling backoff, and then reads the stream from the current moment again, telling every estimate to treat its next quote as a new baseline, because the quotes it missed cannot be told apart from trades.

This program uses a Redis stand-in whose `XREAD` raises `redis.ConnectionError` on its second and third calls, and a stop event stand-in that allows five passes and, instead of sleeping, prints how long it was asked to wait. The logger prints its messages. Before the loop starts, it also calls `rebase_everything` directly on one estimate to show what the loop does after an outage.

Notice the backoff going from one second to two, the stream being read from `$` again after the outage, and that the estimate takes a fresh baseline instead of reading the gap as trading.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/virtual_book/VirtualBook/example_3_riding_out_a_redis_outage.py
"""

import json

import redis

from unified_broker_interface.utilities.order_engine.utilities.virtual_book import (
    QUOTES_STREAM_KEY,
    VirtualBook,
)


class StandInPipeline:
    """A Redis pipeline that does nothing when executed, since this program does not read the written estimates.

    Attributes:
        writes (int): How many writes were queued.
    """

    def __init__(self):
        """Builds an empty pipeline.

        Returns:
            None: This method returns nothing.
        """
        self.writes = 0

    def hset(self, key, field, value):
        """Counts one hash write.

        Args:
            key (str): The hash.
            field (str): The field.
            value (str): The value.

        Returns:
            None: This method returns nothing.
        """
        self.writes = self.writes + 1

    def execute(self):
        """Pretends to send the writes.

        Returns:
            list: Nothing, as no reply is read.
        """
        return []


class FlakyRedis:
    """A Redis stand-in whose stream read fails on chosen calls, and which returns one new quote on every other call.

    Attributes:
        failing_reads (set): The 1-based `XREAD` calls that raise.
        reads (int): How many `XREAD` calls have been made.
        read_after (list): The id each call asked to read after.
    """

    def __init__(self, failing_reads):
        """Builds the stand-in.

        Args:
            failing_reads (set): The 1-based `XREAD` calls that raise.

        Returns:
            None: This method returns nothing.
        """
        self.failing_reads = failing_reads
        self.reads = 0
        self.read_after = []

    def hget(self, key, field):
        """Reads no stored estimate.

        Args:
            key (str): The hash.
            field (str): The field.

        Returns:
            None: Nothing is stored.
        """
        return None

    def hkeys(self, key):
        """Lists no stored estimates.

        Args:
            key (str): The hash.

        Returns:
            list: Always empty.
        """
        return []

    def pipeline(self, transaction=True):
        """Starts a pipeline.

        Args:
            transaction (bool): Ignored.

        Returns:
            StandInPipeline: The pipeline.
        """
        return StandInPipeline()

    def xread(self, streams, count=None, block=None):
        """Returns one INFY quote, or raises on a failing call.

        Args:
            streams (dict): The stream key and the id to read after.
            count (int | None): Ignored.
            block (int | None): Ignored.

        Returns:
            list: One (stream key, entries) pair.

        Raises:
            redis.ConnectionError: On the calls listed in `failing_reads`.
        """
        self.reads = self.reads + 1
        self.read_after.append(streams[QUOTES_STREAM_KEY])
        if self.reads in self.failing_reads:
            raise redis.ConnectionError('Connection refused')
        quote = {
            'instrument_id': 'NSE:INFY',
            'broker': 'zerodha',
            'volume': 100000 + self.reads * 1000,
            'last_price': 98.0,
            'depth': {
                'buy': [
                    {
                        'price': 98.0,
                        'quantity': 12000,
                    },
                ],
                'sell': [
                    {
                        'price': 98.1,
                        'quantity': 500,
                    },
                ],
            },
        }
        return [
            (
                QUOTES_STREAM_KEY,
                [
                    (
                        f'{self.reads}-0',
                        {
                            'quote': json.dumps(quote),
                        },
                    ),
                ],
            ),
        ]


class StandInParentStore:
    """The engine's parent cache holding one held virtual limit buy.

    Attributes:
        document (dict): The held parent.
    """

    def __init__(self):
        """Builds the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.document = {
            'parent_order_id': 'parent-1',
            'synthetic_type': 'virtual_limit',
            'instrument_id': 'NSE:INFY',
            'body': {
                'transaction_type': 'BUY',
                'price': 98,
                'quantity': 500,
            },
            'parameters': {},
            'legs': [],
        }

    def open_parent_ids(self):
        """The ids of every open parent.

        Returns:
            list: The one id.
        """
        return [
            'parent-1',
        ]

    def parent(self, parent_order_id):
        """One parent's document.

        Args:
            parent_order_id (str): The id.

        Returns:
            dict: The held parent.
        """
        return self.document


class CountingStop:
    """A stop event stand-in that is set after a number of passes and prints each wait instead of sleeping.

    Attributes:
        passes_left (int): How many more times `is_set` answers False.
    """

    def __init__(self, passes):
        """Builds the stand-in.

        Args:
            passes (int): How many passes to allow.

        Returns:
            None: This method returns nothing.
        """
        self.passes_left = passes

    def is_set(self):
        """Whether the loop should stop.

        Returns:
            bool: True once the passes are used up.
        """
        if self.passes_left <= 0:
            return True
        self.passes_left = self.passes_left - 1
        return False

    def wait(self, seconds):
        """Prints the wait instead of sleeping.

        Args:
            seconds (int): How long the loop asked to wait.

        Returns:
            bool: False, as if the wait timed out.
        """
        print(f'  (waits {seconds} seconds)')
        return False


class PrintingLogger:
    """A logger that prints each message."""

    def error(self, message):
        """Prints an error.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        print(f'ERROR {message}')

    def info(self, message):
        """Prints an information message.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        print(f'INFO {message}')


class RedisOutageExample:
    """Runs the book's loop for five passes, two of which meet a Redis outage.

    Attributes:
        cache (FlakyRedis): The failing Redis stand-in.
        book (VirtualBook): The book being shown.
    """

    def __init__(self):
        """Builds the book over the failing Redis.

        Returns:
            None: This method returns nothing.
        """
        self.cache = FlakyRedis(
            {
                2,
                3,
            },
        )
        self.book = VirtualBook(self.cache, StandInParentStore(), PrintingLogger())

    def run(self):
        """Shows `rebase_everything` on its own, then runs the loop.

        Returns:
            None: This method returns nothing.
        """
        self.book.refresh()
        estimate = self.book.estimates['parent-1']
        estimate.needs_baseline = False
        self.book.rebase_everything()
        print(f'After rebase_everything, the estimate takes a new baseline: {estimate.needs_baseline}')
        exit_code = self.book.run(CountingStop(5))
        print(f'Exit code: {exit_code}')
        print(f'XREAD asked to read after: {self.cache.read_after}')
        estimate = self.book.estimates['parent-1']
        print(f'Estimate: ahead={estimate.ahead} last_volume={estimate.last_volume} updates={estimate.updates}')


if __name__ == '__main__':
    RedisOutageExample().run()
