"""Reads the live quote of every instrument the open parents watch in one Redis call, and hands each parent the quotes it asked for.

Some synthetic order types watch the market rather than wait for a fill, such as a trailing stop. Those types set `WANTS_PRICES`, and about once a second the engine asks a `PriceTicker` to `tick`. The ticker collects the instruments every watching parent names, reads all their quotes from the `unified:quotes:live` hash in one `HMGET`, and gives each parent a dictionary of the quotes it cares about. A parent's instruments are its own instrument, the instrument in its `watch_instrument_id` parameter, and the instrument of every leg.

This program sets up three open parents. Two trade the same Nifty option, one of them also watching the Nifty index, and a third is a spread whose second leg trades a different option. A plain order that does not watch prices is skipped. A stand-in Redis client holds the quotes and records every `HMGET` it is sent, which shows that three instruments cost one call. The instrument ids are readable names rather than the UUIDs `unified.instruments` really uses, so the output is easy to follow. The quote for the second option is missing and the index's quote is unreadable text, so both reach the parents as None, which is how a type learns that a feed has not started yet.

So that the output does not depend on the time of day, the program adds one small order type of its own to the registry, `example_price_watcher`, which prints the last price of each quote it is given and acts when its own instrument trades at or above a level. A stand-in parent store holds the records. The program needs no broker, no data store and no network.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/price_ticker/PriceTicker/example_1_one_read_for_every_watcher.py
"""

import json
import logging

from unified_broker_interface.utilities.order_engine.base import (
    SyntheticOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.price_ticker import (
    PriceTicker,
)
from unified_broker_interface.utilities.order_engine.utilities.registry import (
    SYNTHETIC_ORDER_CLASSES,
)

NIFTY_INDEX = 'nifty-50-index'
NIFTY_CALL = 'nifty-2026-10-06-25000-ce'
NIFTY_PUT = 'nifty-2026-10-06-24500-pe'


class PriceWatcher(SyntheticOrder):
    """A small order type that watches prices, for this program only.

    Attributes:
        SYNTHETIC_TYPE (str): The name the registry knows it by.
        WANTS_PRICES (bool): True, so the ticker gives it quotes.
    """

    SYNTHETIC_TYPE = 'example_price_watcher'
    WANTS_PRICES = True

    def on_price_tick(self, quotes, now):
        """Prints the quotes it was given and acts when its own instrument reaches its level.

        Args:
            quotes (dict): The quote for each instrument the parent watches, with None where there was none.
            now (float): The time of the tick, in seconds since the epoch.

        Returns:
            bool: True when the parent acted.
        """
        shown = []
        for instrument_id, quote in quotes.items():
            if quote is None:
                shown.append(f'{instrument_id}=None')
            else:
                shown.append(f'{instrument_id}={quote["last_price"]}')
        print(f'{self.parent.parent_order_id} sees {", ".join(shown)}')
        own = quotes.get(self.parent.instrument_id)
        if own is None:
            return False
        return own['last_price'] >= self.parent.parameters['level']


class QuotesRedis:
    """A stand-in Redis client holding the live quotes hash and recording each read.

    Attributes:
        hashes (dict): Each hash key to its fields.
        reads (list): The instruments asked for by each `HMGET`, in order.
    """

    def __init__(self, quotes):
        """Builds the client with one hash of quotes.

        Args:
            quotes (dict): Each instrument id to its quote text.

        Returns:
            None: This method returns nothing.
        """
        self.hashes = {
            'unified:quotes:live': quotes,
        }
        self.reads = []

    def hmget(self, key, fields):
        """Reads several fields of one hash.

        Args:
            key (str): The hash.
            fields (list): The fields.

        Returns:
            list: Each field's value, or None where it is missing.
        """
        self.reads.append(list(fields))
        stored = self.hashes.get(key, {})
        values = []
        for field in fields:
            values.append(stored.get(field))
        return values


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


class OneReadForEveryWatcherExample:
    """Ticks three watching parents once and prints the quotes each was given.

    Attributes:
        cache (QuotesRedis): The stand-in Redis client.
        documents (dict): Each parent order id to its record.
        ticker (PriceTicker): The ticker being shown.
    """

    def __init__(self):
        """Adds the example type to the registry and builds the ticker over four parents.

        Returns:
            None: This method returns nothing.
        """
        SYNTHETIC_ORDER_CLASSES[PriceWatcher.SYNTHETIC_TYPE] = PriceWatcher
        call_quote = {
            'instrument_id': NIFTY_CALL,
            'broker': 'zerodha',
            'symbol': 'NIFTY',
            'last_price': 132.4,
            'stale': False,
        }
        quotes = {
            NIFTY_CALL: json.dumps(call_quote),
            NIFTY_INDEX: 'not json',
        }
        self.cache = QuotesRedis(quotes)
        self.documents = {
            'parent-1': {
                'parent_order_id': 'parent-1',
                'synthetic_type': 'example_price_watcher',
                'state': 'working',
                'instrument_id': NIFTY_CALL,
                'parameters': {
                    'level': 130.0,
                },
                'legs': [],
            },
            'parent-2': {
                'parent_order_id': 'parent-2',
                'synthetic_type': 'example_price_watcher',
                'state': 'working',
                'instrument_id': NIFTY_CALL,
                'parameters': {
                    'level': 140.0,
                    'watch_instrument_id': NIFTY_INDEX,
                },
                'legs': [],
            },
            'parent-3': {
                'parent_order_id': 'parent-3',
                'synthetic_type': 'example_price_watcher',
                'state': 'working',
                'instrument_id': NIFTY_CALL,
                'parameters': {
                    'level': 200.0,
                },
                'legs': [
                    {
                        'leg_id': 'leg-1',
                        'instrument_id': NIFTY_CALL,
                    },
                    {
                        'leg_id': 'leg-2',
                        'instrument_id': NIFTY_PUT,
                    },
                ],
            },
            'parent-4': {
                'parent_order_id': 'parent-4',
                'synthetic_type': 'simple',
                'state': 'working',
                'instrument_id': NIFTY_PUT,
                'parameters': {},
                'legs': [],
            },
        }
        self.ticker = PriceTicker(
            self.cache,
            DictionaryParentStore(self.documents),
            None,
            None,
            logging.getLogger('example'),
        )

    def run(self):
        """Lists what is watched, ticks once and prints the counts.

        Returns:
            None: This method returns nothing.
        """
        priced = self.ticker.priced_types()
        print(f'example_price_watcher wants prices: {"example_price_watcher" in priced}')
        print(f'Due a second after the last tick: {self.ticker.due(self.ticker.ticked_at + 1.0)}')
        print(f'parent-2 watches {self.ticker.instruments_of(self.documents["parent-2"])}')
        print(f'parent-3 watches {self.ticker.instruments_of(self.documents["parent-3"])}')
        documents, instrument_ids = self.ticker.watching(priced)
        print(f'Watching parents: {len(documents)}, instruments: {instrument_ids}')
        acted = self.ticker.tick()
        print(f'Parents that acted: {acted}')
        print(f'HMGET calls: {len(self.cache.reads)}, instruments in the call: {self.cache.reads[0]}')
        print(f'Quotes read so far: {self.ticker.quotes_read}')
        print(f'Reading no instruments sends nothing: {self.ticker.quotes([])}')


if __name__ == '__main__':
    OneReadForEveryWatcherExample().run()
