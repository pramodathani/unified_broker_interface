"""Runs the synthetic limit order book over a short quote stream and shows the queue estimate it writes for one held order.

A `VirtualBook` keeps one queue estimate for every held `virtual_limit` order, moves it with each quote for that order's instrument, and writes it to the Redis hash `unified:orders:virtual_queue` for the order engine to read. This program holds one buy of 500 INFY at 98.00 and puts three quotes on the stream: one for INFY that sets the baseline, one for another instrument that the book skips, and one for INFY that shows 3,000 traded at 98.00.

The first pass uses `run_once`, which reads the held orders, reads the stream and writes what changed. The second pass does the same three steps by hand with `read_quotes` and `write_changed`, after two more quotes arrive, one of them an entry whose `quote` field is not JSON and is skipped by `apply_entry`. Finally it hands `apply_entry` a quote for an instrument nobody holds, which it ignores. Two small stand-ins replace Redis and the engine's parent cache, so nothing is sent anywhere: the Redis stand-in keeps hashes in dictionaries and hands out stream entries from a list.

Notice that the book reads five entries in all but uses only three, and that the stored estimate has 9,000 ahead after the trade.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/virtual_book/VirtualBook/example_1_one_pass_over_the_quote_stream.py
"""

import json
import logging

from unified_broker_interface.utilities.order_engine.utilities.virtual_book import (
    ESTIMATES_KEY,
    QUOTES_STREAM_KEY,
    VirtualBook,
)


class StandInPipeline:
    """A Redis pipeline that writes into the stand-in's hashes when executed.

    Attributes:
        cache (StandInRedis): The stand-in written to.
        writes (list): The queued (key, field, value) writes.
    """

    def __init__(self, cache):
        """Builds an empty pipeline.

        Args:
            cache (StandInRedis): The stand-in written to.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.writes = []

    def hset(self, key, field, value):
        """Queues one hash write.

        Args:
            key (str): The hash.
            field (str): The field.
            value (str): The value.

        Returns:
            None: This method returns nothing.
        """
        self.writes.append((key, field, value))

    def execute(self):
        """Applies every queued write.

        Returns:
            list: One True per write.
        """
        results = []
        for key, field, value in self.writes:
            self.cache.hashes.setdefault(key, {})[field] = value
            results.append(True)
        return results


class StandInRedis:
    """The few Redis commands the book uses, over dictionaries and a list of stream entries.

    Attributes:
        hashes (dict): Each hash's fields, by key.
        stream (list): The (entry id, fields) pairs on the quote stream, oldest first.
    """

    def __init__(self):
        """Builds an empty stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.hashes = {}
        self.stream = []

    def hget(self, key, field):
        """Reads one hash field.

        Args:
            key (str): The hash.
            field (str): The field.

        Returns:
            str | None: The value.
        """
        return self.hashes.get(key, {}).get(field)

    def hkeys(self, key):
        """Lists one hash's fields.

        Args:
            key (str): The hash.

        Returns:
            list: The fields.
        """
        return list(self.hashes.get(key, {}))

    def hdel(self, key, *fields):
        """Removes hash fields.

        Args:
            key (str): The hash.
            *fields (str): The fields.

        Returns:
            int: How many were removed.
        """
        removed = 0
        for field in fields:
            if self.hashes.get(key, {}).pop(field, None) is not None:
                removed = removed + 1
        return removed

    def pipeline(self, transaction=True):
        """Starts a pipeline.

        Args:
            transaction (bool): Ignored.

        Returns:
            StandInPipeline: The pipeline.
        """
        return StandInPipeline(self)

    def xread(self, streams, count=None, block=None):
        """Returns the stream entries after the id asked for, treating `$` as the start of the list.

        Args:
            streams (dict): The stream key and the id to read after.
            count (int | None): Ignored.
            block (int | None): Ignored.

        Returns:
            list: One (stream key, entries) pair, or an empty list.
        """
        after = streams[QUOTES_STREAM_KEY]
        entries = []
        for entry_id, fields in self.stream:
            if after == '$' or entry_id > after:
                entries.append((entry_id, fields))
        if not entries:
            return []
        return [
            (QUOTES_STREAM_KEY, entries),
        ]


class StandInParentStore:
    """The engine's parent cache, as a dictionary of open parents.

    Attributes:
        documents (dict): Each open parent's document, by id.
    """

    def __init__(self, documents):
        """Builds the stand-in.

        Args:
            documents (dict): Each open parent's document, by id.

        Returns:
            None: This method returns nothing.
        """
        self.documents = documents

    def open_parent_ids(self):
        """The ids of every open parent.

        Returns:
            list: The ids, sorted.
        """
        return sorted(self.documents)

    def parent(self, parent_order_id):
        """One parent's document.

        Args:
            parent_order_id (str): The id.

        Returns:
            dict | None: The document.
        """
        return self.documents.get(parent_order_id)


class OnePassExample:
    """Holds one virtual limit buy, feeds the book quotes, and prints the estimate it stores.

    Attributes:
        cache (StandInRedis): The stand-in Redis.
        book (VirtualBook): The book being shown.
    """

    def __init__(self):
        """Builds the book over one held buy of 500 at 98.00.

        Returns:
            None: This method returns nothing.
        """
        self.cache = StandInRedis()
        held_buy = {
            'parent_order_id': 'parent-1',
            'synthetic_type': 'virtual_limit',
            'state': 'received',
            'instrument_id': 'NSE:INFY',
            'body': {
                'transaction_type': 'BUY',
                'order_type': 'LIMIT',
                'price': 98,
                'quantity': 500,
            },
            'parameters': {
                'type': 'virtual_limit',
            },
            'legs': [],
        }
        parent_store = StandInParentStore(
            {
                'parent-1': held_buy,
            },
        )
        self.book = VirtualBook(self.cache, parent_store, logging.getLogger('example'))

    def entry(self, entry_id, instrument_id, volume, last_price, bid_quantity):
        """Builds one quote stream entry with the quote as JSON, as the unified quote script writes it.

        Args:
            entry_id (str): The stream entry id.
            instrument_id (str): The instrument.
            volume (int): The day's volume.
            last_price (float): The last traded price.
            bid_quantity (int): The quantity bid at 98.00.

        Returns:
            tuple: The entry id and its fields.
        """
        quote = {
            'instrument_id': instrument_id,
            'broker': 'zerodha',
            'volume': volume,
            'last_price': last_price,
            'received_at': 1759200000.0,
            'depth': {
                'buy': [
                    {
                        'price': 98.0,
                        'quantity': bid_quantity,
                    },
                ],
                'sell': [
                    {
                        'price': 98.2,
                        'quantity': 800,
                    },
                ],
            },
        }
        return (
            entry_id,
            {
                'quote': json.dumps(quote),
            },
        )

    def show(self, label):
        """Prints the book's counters and the stored estimate.

        Args:
            label (str): Which pass this was.

        Returns:
            None: This method returns nothing.
        """
        stored = json.loads(self.cache.hget(ESTIMATES_KEY, 'parent-1'))
        print(f'{label}: read {self.book.quotes_read}, used {self.book.quotes_used}, read up to {self.book.last_entry_id}')
        print(f'  stored estimate: ahead={stored["ahead"]} queue_filled={stored["queue_filled"]} updates={stored["updates"]}')

    def run(self):
        """Runs one full pass, then a second pass step by step.

        Returns:
            None: This method returns nothing.
        """
        self.cache.stream = [
            self.entry('1-0', 'NSE:INFY', 100000, 98.1, 12000),
            self.entry('2-0', 'NSE:TCS', 999999, 3050.0, 0),
            self.entry('3-0', 'NSE:INFY', 103000, 98.0, 9000),
        ]
        print(f'Refresh due before the first pass: {self.book.is_refresh_due()}')
        read = self.book.run_once()
        print(f'Held orders by instrument: {self.book.by_instrument}')
        self.show(f'First pass read {read} entries')
        print(f'Refresh due straight afterwards: {self.book.is_refresh_due()}')
        self.cache.stream.append(
            (
                '4-0',
                {
                    'quote': 'not json',
                },
            ),
        )
        self.cache.stream.append(self.entry('5-0', 'NSE:INFY', 103500, 98.0, 8500))
        read = self.book.read_quotes()
        print(f'Waiting to be written: {sorted(self.book.changed)}')
        written = self.book.write_changed()
        self.show(f'Second pass read {read} entries and wrote {written}')
        other_quote = self.entry('6-0', 'NSE:TCS', 1000000, 3051.0, 0)
        self.book.apply_entry(other_quote[1])
        print(f'A TCS quote applied directly moves nothing: used is still {self.book.quotes_used}')


if __name__ == '__main__':
    OnePassExample().run()
