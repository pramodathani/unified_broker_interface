"""Spells Stoxkart instruments as `EXCHANGE:TOKEN`, reading which exchange lists each token from Stoxkart's own master.

Some of Stoxkart's tokens appear under more than one of its exchanges, so the spelling reads `stoxkart:instruments:master` once and keeps, for each token, the exchanges that list it. The canonical exchange narrows the choice, and where both a cash and a currency exchange remain, the segment decides. This program holds a four-row master in a stand-in Redis, in which token 4438 is listed under both `NSE` and `NSECD`.

It needs no data store, no network and no broker login.

Notice that token 4438 becomes `NSE:4438` for the equity, because the segment says cash, and that the NFO option is spelled from the master's `NFO` row.

Run it from the project root:

    python examples/unified_broker_interface/utilities/quote_subscriptions/stoxkart/StoxkartQuoteSubscription/example_1_exchange_from_the_master.py
"""

import json

from unified_broker_interface.utilities.quote_subscriptions.stoxkart import (
    StoxkartQuoteSubscription,
)


class StandInRedis:
    """Answers the two reads the spelling makes: the master's meta key and a scan of the master hash.

    Attributes:
        strings (dict): String keys to their values.
        hashes (dict): Hash keys to their fields.
    """

    def __init__(self, strings, hashes):
        """Holds the keys.

        Args:
            strings (dict): String keys to their values.
            hashes (dict): Hash keys to their fields.

        Returns:
            None: This method returns nothing.
        """
        self.strings = strings
        self.hashes = hashes

    def get(self, key):
        """A string key's value.

        Args:
            key (str): The key.

        Returns:
            str | None: The value, or None when absent.
        """
        return self.strings.get(key)

    def hscan_iter(self, key, count=None):
        """Every field of a hash.

        Args:
            key (str): The hash's key.
            count (int | None): Unused.

        Yields:
            tuple: A field and its value.
        """
        del count
        yield from self.hashes.get(key, {}).items()


class ExchangeFromTheMasterExample:
    """Spells an equity and an option against a small stand-in master.

    Attributes:
        spelling (StoxkartQuoteSubscription): The spelling being shown.
    """

    def __init__(self):
        """Builds the stand-in master and the spelling.

        Returns:
            None: This method returns nothing.
        """
        meta = {
            'columns': [
                'exchange',
                'market_segment_id',
                'token',
                'symbol',
            ],
        }
        master = {
            'NSE:RELIANCE': json.dumps(['NSE', 1, '2885', 'RELIANCE']),
            'NSE:SOMESTOCK': json.dumps(['NSE', 1, '4438', 'SOMESTOCK']),
            'NSECD:USDINR26NOVFUT': json.dumps(['NSECD', 3, '4438', 'USDINR']),
            'NFO:NIFTY26NOV24000CE': json.dumps(['NFO', 2, '35001', 'NIFTY']),
        }
        cache = StandInRedis(
            {
                'stoxkart:instruments:meta': json.dumps(meta),
            },
            {
                'stoxkart:instruments:master': master,
            },
        )
        self.spelling = StoxkartQuoteSubscription(cache)

    def run(self):
        """Prints the member for each instrument.

        Returns:
            None: This method returns nothing.
        """
        rows = [
            ('RELIANCE', 'nse', 'nse_equities', 'security', '2885'),
            ('SOMESTOCK', 'nse', 'nse_equities', 'security', '4438'),
            ('NIFTY 26 NOV 24000 CE', 'nse', 'nse_equity_index_options', 'option', '35001'),
        ]
        print(f'Broker: {StoxkartQuoteSubscription.BROKER_NAME}')
        for label, exchange, segment, shape, token in rows:
            identity = {
                'exchange': exchange,
                'segment': segment,
                'shape': shape,
            }
            print(f'{label}: {self.spelling.member(identity, token, None)}')


if __name__ == '__main__':
    ExchangeFromTheMasterExample().run()
