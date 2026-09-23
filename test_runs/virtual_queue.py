"""Offline checks of the queue estimate behind the synthetic limit order book.

`unified_broker_interface/utilities/order_engine/utilities/virtual_queue.py` is fed scripted sequences of unified quotes, so no Redis, database, credentials or network are used. The checks cover joining a queue behind the visible depth, trades at and through the price, cancellations ahead, arrivals behind, a price beyond the visible depth, a change of the broker owning the quote, a stale quote, a new session, the opposite touch reaching the price, the sell side, and storing an estimate and reading it back. The virtual book that keeps the estimates is run against a stand-in Redis and parent cache, for which orders it follows, which quotes it uses, and when it forgets an estimate.

Typical usage:

    python -m test_runs.virtual_queue
"""

import decimal
import json
import logging
import sys

from unified_broker_interface.utilities.order_engine.utilities.virtual_book import (
    ESTIMATES_KEY,
    QUOTES_STREAM_KEY,
    VirtualBook,
)
from unified_broker_interface.utilities.order_engine.utilities.virtual_queue import (
    VirtualQueue,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'
OTHER_INSTRUMENT_ID = '11111111-1111-5111-8111-000000000002'


class StandInPipeline:
    """A Redis pipeline that writes straight into the stand-in's hashes when executed.

    Attributes:
        cache (StandInCache): The cache written to.
        writes (list): The (key, field, value) writes queued so far.
    """

    def __init__(self, cache):
        """Builds the pipeline.

        Args:
            cache (StandInCache): The cache written to.

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
        for key, field, value in self.writes:
            self.cache.hashes.setdefault(key, {})[field] = value
        return [True] * len(self.writes)


class StandInCache:
    """The few Redis commands the virtual book uses, over dictionaries and one list of stream entries.

    Attributes:
        hashes (dict): Each hash's fields, by key.
        stream (list): The (entry id, fields) pairs on the quote stream, oldest first.
        reads (list): The id each `xread` asked to read after.
    """

    def __init__(self):
        """Builds an empty stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.hashes = {}
        self.stream = []
        self.reads = []

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
        del transaction
        return StandInPipeline(self)

    def xread(self, streams, count=None, block=None):
        """Returns every stream entry not yet read, as `XREAD` would, treating `$` as the start of the list.

        Args:
            streams (dict): The stream key and the id to read after.
            count (int | None): Ignored, since the stand-in's streams are short.
            block (int | None): Ignored.

        Returns:
            list: One (stream key, entries) pair, or an empty list.
        """
        del count, block
        after = streams[QUOTES_STREAM_KEY]
        self.reads.append(after)
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
    """The engine's parent cache, as a dictionary of documents that are all open.

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


class VirtualQueueSuite:
    """Runs every check of the queue estimate and reports how many passed.

    Attributes:
        passed (int): How many checks passed.
        failed (list): The names of the checks that failed.
        received_at (float): The receive time the next quote carries.
    """

    def __init__(self):
        """Builds the suite.

        Returns:
            None: This method returns nothing.
        """
        self.passed = 0
        self.failed = []
        self.received_at = 1790150400.0

    def check(self, name, found, expected):
        """Records whether one check gave the expected value.

        Args:
            name (str): The check's name.
            found (object): What the code gave.
            expected (object): What it should have given.

        Returns:
            None: This method returns nothing.
        """
        if found == expected:
            self.passed += 1
            return
        self.failed.append(name)
        print(f'FAILED {name}')
        print(f'  expected {expected!r}')
        print(f'  found    {found!r}')

    def quote(
        self,
        volume,
        last_price,
        bids,
        offers,
        broker='zerodha',
        stale=False,
    ):
        """A unified quote carrying only what the estimate reads.

        Args:
            volume (int): The day's volume.
            last_price (float): The last traded price.
            bids (list): (price, quantity) pairs, best first.
            offers (list): (price, quantity) pairs, best first.
            broker (str): The broker owning the quote.
            stale (bool): Whether the quote is marked stale.

        Returns:
            dict: The quote.
        """
        self.received_at = self.received_at + 1.0
        buy_levels = []
        for price, quantity in bids:
            buy_levels.append({
                'price': price,
                'quantity': quantity,
                'orders': 1,
            })
        sell_levels = []
        for price, quantity in offers:
            sell_levels.append({
                'price': price,
                'quantity': quantity,
                'orders': 1,
            })
        return {
            'instrument_id': INSTRUMENT_ID,
            'broker': broker,
            'volume': volume,
            'last_price': last_price,
            'depth': {
                'buy': buy_levels,
                'sell': sell_levels,
            },
            'stale': stale,
            'received_at': self.received_at,
        }

    def bids_with_98_at(self, quantity_at_98):
        """Five bid levels from 100 down to 98, with a chosen quantity at 98.

        Args:
            quantity_at_98 (int): The quantity resting at 98.

        Returns:
            list: The (price, quantity) pairs.
        """
        return [
            (100.0, 1000),
            (99.5, 2000),
            (99.0, 3000),
            (98.5, 4000),
            (98.0, quantity_at_98),
        ]

    def offers_from_101(self):
        """Five offer levels from 101 upwards.

        Returns:
            list: The (price, quantity) pairs.
        """
        return [
            (101.0, 1000),
            (101.5, 2000),
            (102.0, 3000),
            (102.5, 4000),
            (103.0, 5000),
        ]

    def buy_at_98(self, quantity=500):
        """A held buy at 98.

        Args:
            quantity (int): The quantity.

        Returns:
            VirtualQueue: The estimate.
        """
        return VirtualQueue(
            'parent-1',
            INSTRUMENT_ID,
            'BUY',
            decimal.Decimal('98.00'),
            quantity,
        )

    def joined_buy_at_98(self, quantity_at_98, quantity=500):
        """A held buy at 98 that has joined the queue behind a chosen quantity, at a volume of 100,000.

        Args:
            quantity_at_98 (int): The quantity resting at 98 when it joins.
            quantity (int): The order's quantity.

        Returns:
            VirtualQueue: The estimate.
        """
        estimate = self.buy_at_98(quantity)
        estimate.update(self.quote(
            100000,
            100.0,
            self.bids_with_98_at(quantity_at_98),
            self.offers_from_101(),
        ))
        return estimate

    def run(self):
        """Runs every check and prints how many passed.

        Returns:
            int: 0 when every check passed, 1 when any failed.
        """
        self.an_order_joins_behind_the_visible_depth()
        self.trades_at_the_price_serve_the_queue_ahead_first()
        self.what_trades_after_the_queue_fills_the_order()
        self.cancellations_shorten_the_queue_by_their_share()
        self.arrivals_join_behind_and_change_nothing()
        self.a_trade_through_the_price_fills_everything()
        self.trades_above_the_price_do_not_reach_it()
        self.a_price_beyond_the_visible_depth_waits_to_be_seen()
        self.a_price_better_than_the_best_bid_is_first_in_line()
        self.a_change_of_owner_only_takes_a_baseline()
        self.a_stale_quote_is_ignored()
        self.a_new_session_joins_the_queue_again()
        self.the_opposite_touch_fills_the_rest_but_not_the_queue()
        self.a_sell_is_the_mirror_image()
        self.a_stored_estimate_reads_back_and_rebases()
        self.the_queue_never_fills_more_than_the_order()
        self.the_book_follows_only_held_virtual_limits()
        self.the_book_moves_estimates_on_their_own_instrument()
        self.the_book_forgets_a_parent_that_has_closed()

        total = self.passed + len(self.failed)
        print(f'{self.passed}/{total} checks passed.')
        if self.failed:
            return 1
        return 0

    def an_order_joins_behind_the_visible_depth(self):
        """A new estimate's first quote puts it behind whatever is resting at its price.

        Returns:
            None: This method returns nothing.
        """
        estimate = self.joined_buy_at_98(12000)
        self.check('an order joins behind the visible depth', estimate.ahead, 12000)
        self.check('joining fills nothing', estimate.queue_filled, 0)

    def trades_at_the_price_serve_the_queue_ahead_first(self):
        """Volume that traded at the price comes off the queue ahead before the order sees any.

        Returns:
            None: This method returns nothing.
        """
        estimate = self.joined_buy_at_98(12000)
        estimate.update(self.quote(
            103000,
            98.0,
            self.bids_with_98_at(9000),
            self.offers_from_101(),
        ))
        self.check('3,000 traded at 98 leave 9,000 ahead', estimate.ahead, 9000)
        self.check('the order is not reached yet', estimate.queue_filled, 0)

    def what_trades_after_the_queue_fills_the_order(self):
        """Once the queue ahead is gone, whatever else traded at the price fills the order.

        Returns:
            None: This method returns nothing.
        """
        estimate = self.joined_buy_at_98(1000)
        estimate.update(self.quote(
            101300,
            98.0,
            self.bids_with_98_at(0),
            self.offers_from_101(),
        ))
        self.check('the queue ahead is used up', estimate.ahead, 0)
        self.check('the 300 left over fill the order', estimate.queue_filled, 300)
        self.check('filled counts the queue fill', estimate.filled(), 300)

    def cancellations_shorten_the_queue_by_their_share(self):
        """What left the level without trading comes off the queue ahead in proportion to the share ahead.

        Returns:
            None: This method returns nothing.
        """
        estimate = self.joined_buy_at_98(12000)
        estimate.update(self.quote(
            100000,
            100.0,
            self.bids_with_98_at(18000),
            self.offers_from_101(),
        ))
        self.check('6,000 arriving behind leave 12,000 ahead', estimate.ahead, 12000)
        estimate.update(self.quote(
            100000,
            100.0,
            self.bids_with_98_at(9000),
            self.offers_from_101(),
        ))
        self.check(
            '9,000 cancelled from a level two-thirds ahead take 6,000 from ahead',
            estimate.ahead,
            6000,
        )

    def arrivals_join_behind_and_change_nothing(self):
        """A level that grows has grown behind the order.

        Returns:
            None: This method returns nothing.
        """
        estimate = self.joined_buy_at_98(5000)
        estimate.update(self.quote(
            100000,
            100.0,
            self.bids_with_98_at(20000),
            self.offers_from_101(),
        ))
        self.check('arrivals leave the queue ahead alone', estimate.ahead, 5000)

    def a_trade_through_the_price_fills_everything(self):
        """A trade below a buy's price could only happen after every bid at the price was filled.

        Returns:
            None: This method returns nothing.
        """
        estimate = self.joined_buy_at_98(12000)
        estimate.update(self.quote(
            100100,
            97.5,
            [
                (97.5, 500),
            ],
            [
                (98.5, 700),
            ],
        ))
        self.check('a trade at 97.50 fills the whole buy at 98', estimate.queue_filled, 500)
        self.check('nothing is left ahead', estimate.ahead, 0)
        self.check('the offer never reached 98', estimate.touched_at, None)

    def trades_above_the_price_do_not_reach_it(self):
        """Volume that traded above a buy's price says nothing about the queue at the price.

        Returns:
            None: This method returns nothing.
        """
        estimate = self.joined_buy_at_98(12000)
        estimate.update(self.quote(
            150000,
            100.0,
            self.bids_with_98_at(12000),
            self.offers_from_101(),
        ))
        self.check('trades at 100 leave the queue at 98 alone', estimate.ahead, 12000)
        self.check('trades at 100 fill nothing at 98', estimate.queue_filled, 0)

    def a_price_beyond_the_visible_depth_waits_to_be_seen(self):
        """A price past the fifth level has no known place until the book brings it into view.

        Returns:
            None: This method returns nothing.
        """
        estimate = self.buy_at_98()
        full_book_above_98 = [
            (100.0, 1000),
            (99.75, 1000),
            (99.5, 1000),
            (99.25, 1000),
            (99.0, 1000),
        ]
        estimate.update(self.quote(
            100000,
            100.0,
            full_book_above_98,
            self.offers_from_101(),
        ))
        self.check('a price beyond five levels has no place yet', estimate.ahead, None)
        estimate.update(self.quote(
            100500,
            98.0,
            full_book_above_98,
            self.offers_from_101(),
        ))
        self.check('an unknown place is not filled by trades at the price', estimate.queue_filled, 0)
        estimate.update(self.quote(
            100500,
            99.0,
            self.bids_with_98_at(4000),
            self.offers_from_101(),
        ))
        self.check('the order joins once the price comes into view', estimate.ahead, 4000)

    def a_price_better_than_the_best_bid_is_first_in_line(self):
        """A buy above the best bid would be a new best bid on its own, with nobody ahead.

        Returns:
            None: This method returns nothing.
        """
        estimate = VirtualQueue(
            'parent-1',
            INSTRUMENT_ID,
            'BUY',
            decimal.Decimal('100.50'),
            500,
        )
        estimate.update(self.quote(
            100000,
            100.0,
            self.bids_with_98_at(1000),
            self.offers_from_101(),
        ))
        self.check('nobody is ahead of a new best bid', estimate.ahead, 0)
        estimate.update(self.quote(
            100200,
            100.5,
            self.bids_with_98_at(1000),
            self.offers_from_101(),
        ))
        self.check('the first 200 traded at 100.50 are the order\'s', estimate.queue_filled, 200)

    def a_change_of_owner_only_takes_a_baseline(self):
        """A quote from a different broker is not compared with the last, because its volume may count differently.

        Returns:
            None: This method returns nothing.
        """
        estimate = self.joined_buy_at_98(12000)
        estimate.update(self.quote(
            400000,
            98.0,
            self.bids_with_98_at(12000),
            self.offers_from_101(),
            broker='dhan',
        ))
        self.check('a new owner\'s volume is not read as trading', estimate.ahead, 12000)
        self.check('a new owner fills nothing', estimate.queue_filled, 0)
        self.check('the new owner is remembered', estimate.last_broker, 'dhan')

    def a_stale_quote_is_ignored(self):
        """A quote whose owner went silent is not read at all.

        Returns:
            None: This method returns nothing.
        """
        estimate = self.joined_buy_at_98(12000)
        changed = estimate.update(self.quote(
            200000,
            97.0,
            self.bids_with_98_at(0),
            self.offers_from_101(),
            stale=True,
        ))
        self.check('a stale quote changes nothing', changed, False)
        self.check('a stale trade through fills nothing', estimate.queue_filled, 0)
        self.check('a stale quote keeps the baseline', estimate.last_volume, 100000)

    def a_new_session_joins_the_queue_again(self):
        """Volume falling means a new session, whose queue starts again from the back.

        Returns:
            None: This method returns nothing.
        """
        estimate = self.joined_buy_at_98(12000)
        estimate.update(self.quote(
            800,
            99.5,
            self.bids_with_98_at(3000),
            self.offers_from_101(),
        ))
        self.check('a new session joins behind today\'s depth', estimate.ahead, 3000)
        self.check('the new session\'s baseline is its own volume', estimate.last_volume, 800)

    def the_opposite_touch_fills_the_rest_but_not_the_queue(self):
        """The offer coming down to a buy's price is when the real order is sent, which is not a queue fill.

        Returns:
            None: This method returns nothing.
        """
        estimate = self.joined_buy_at_98(12000)
        estimate.update(self.quote(
            100000,
            99.0,
            [
                (97.5, 1000),
            ],
            [
                (98.0, 700),
            ],
        ))
        self.check('the touch is recorded', estimate.touched_at, self.received_at)
        self.check('the touch is not a queue fill', estimate.queue_filled, 0)
        self.check('the touch fills the rest', estimate.filled(), 500)
        self.check('the stored estimate says so', estimate.document()['remaining'], 0)

    def a_sell_is_the_mirror_image(self):
        """A sell queues on the offer, fills from trades at its price, and fills whole on a trade above it.

        Returns:
            None: This method returns nothing.
        """
        estimate = VirtualQueue(
            'parent-2',
            INSTRUMENT_ID,
            'SELL',
            decimal.Decimal('102'),
            200,
        )
        estimate.update(self.quote(
            100000,
            100.0,
            self.bids_with_98_at(1000),
            self.offers_from_101(),
        ))
        self.check('a sell joins behind the offer at its price', estimate.ahead, 3000)
        estimate.update(self.quote(
            103100,
            102.0,
            self.bids_with_98_at(1000),
            self.offers_from_101(),
        ))
        self.check('3,100 traded at 102 fill 100 of the sell', estimate.queue_filled, 100)
        estimate.update(self.quote(
            103200,
            102.5,
            self.bids_with_98_at(1000),
            self.offers_from_101(),
        ))
        self.check('a trade at 102.50 fills the rest of the sell', estimate.queue_filled, 200)

    def a_stored_estimate_reads_back_and_rebases(self):
        """An estimate written to Redis reads back the same, and takes its next quote as a baseline.

        Returns:
            None: This method returns nothing.
        """
        estimate = self.joined_buy_at_98(12000)
        stored = estimate.document()
        read_back = VirtualQueue.from_document(stored)
        self.check('a stored estimate reads back the same', read_back.document(), stored)
        self.check('a read-back estimate rebases first', read_back.needs_baseline, True)
        read_back.update(self.quote(
            150000,
            98.0,
            self.bids_with_98_at(12000),
            self.offers_from_101(),
        ))
        self.check('trades missed while stored are not counted', read_back.ahead, 12000)

    def the_queue_never_fills_more_than_the_order(self):
        """However much trades at the price, the order fills its own quantity and no more.

        Returns:
            None: This method returns nothing.
        """
        estimate = self.joined_buy_at_98(0)
        estimate.update(self.quote(
            200000,
            98.0,
            self.bids_with_98_at(0),
            self.offers_from_101(),
        ))
        self.check('the order fills its own quantity', estimate.queue_filled, 500)
        estimate.update(self.quote(
            300000,
            98.0,
            self.bids_with_98_at(0),
            self.offers_from_101(),
        ))
        self.check('and no more afterwards', estimate.queue_filled, 500)

    def parent_document(self, parent_order_id, **overrides):
        """A parent as the engine's cache holds it: a held virtual limit buy of 500 at 98.

        Args:
            parent_order_id (str): The parent's id.
            **overrides: Top-level fields to replace.

        Returns:
            dict: The document.
        """
        document = {
            'parent_order_id': parent_order_id,
            'synthetic_type': 'virtual_limit',
            'state': 'received',
            'instrument_id': INSTRUMENT_ID,
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
        document.update(overrides)
        return document

    def book_with(self, documents):
        """A virtual book over a stand-in Redis and the given open parents.

        Args:
            documents (dict): Each open parent's document, by id.

        Returns:
            tuple: The book (VirtualBook) and its stand-in cache (StandInCache).
        """
        cache = StandInCache()
        book = VirtualBook(
            cache,
            StandInParentStore(documents),
            logging.getLogger('test_runs.virtual_queue'),
        )
        return book, cache

    def stream_entry(self, entry_id, quote):
        """One entry on the unified quote stream.

        Args:
            entry_id (str): The entry id.
            quote (dict): The quote.

        Returns:
            tuple: The entry id and its fields.
        """
        return (
            entry_id,
            {
                'quote': json.dumps(quote),
            },
        )

    def the_book_follows_only_held_virtual_limits(self):
        """Only an open virtual limit that has not fired gets an estimate.

        Returns:
            None: This method returns nothing.
        """
        fired = self.parent_document('fired')
        fired['legs'] = [
            {
                'role': 'entry',
            },
        ]
        book, _ = self.book_with({
            'held': self.parent_document('held'),
            'fired': fired,
            'other_type': self.parent_document(
                'other_type',
                synthetic_type='limit_if_touched',
            ),
        })
        book.refresh()
        self.check('only the held virtual limit is followed', sorted(book.estimates), ['held'])
        self.check('it is filed under its instrument', book.by_instrument, {INSTRUMENT_ID: ['held']})

    def the_book_moves_estimates_on_their_own_instrument(self):
        """A quote for the held order's instrument moves its estimate and is written; another instrument's is skipped.

        Returns:
            None: This method returns nothing.
        """
        book, cache = self.book_with({
            'held': self.parent_document('held'),
        })
        joined = self.quote(
            100000,
            100.0,
            self.bids_with_98_at(12000),
            self.offers_from_101(),
        )
        traded = self.quote(
            103000,
            98.0,
            self.bids_with_98_at(9000),
            self.offers_from_101(),
        )
        elsewhere = dict(traded, instrument_id=OTHER_INSTRUMENT_ID, volume=999999)
        cache.stream = [
            self.stream_entry('1-0', joined),
            self.stream_entry('2-0', elsewhere),
            self.stream_entry('3-0', traded),
        ]
        book.run_once()
        stored = json.loads(cache.hashes[ESTIMATES_KEY]['held'])
        self.check('the book reads all three entries', book.quotes_read, 3)
        self.check('only two are for a held order', book.quotes_used, 2)
        self.check('the stored estimate has 9,000 ahead', stored['ahead'], 9000)
        self.check('the book remembers where it read to', book.last_entry_id, '3-0')

    def the_book_forgets_a_parent_that_has_closed(self):
        """A stored estimate whose parent is no longer open is removed on the next refresh.

        Returns:
            None: This method returns nothing.
        """
        book, cache = self.book_with({
            'held': self.parent_document('held'),
        })
        cache.hashes[ESTIMATES_KEY] = {
            'closed': json.dumps(self.buy_at_98().document()),
        }
        book.refresh()
        self.check('the closed parent\'s estimate is removed', sorted(cache.hashes[ESTIMATES_KEY]), [])
        book.write_changed()
        self.check('the held parent\'s new estimate is written', sorted(cache.hashes[ESTIMATES_KEY]), ['held'])


if __name__ == '__main__':
    sys.exit(VirtualQueueSuite().run())
