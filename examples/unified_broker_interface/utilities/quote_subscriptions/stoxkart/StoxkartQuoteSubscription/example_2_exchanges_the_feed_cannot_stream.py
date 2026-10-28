"""Shows the Stoxkart instruments the broadcast feed cannot stream, so the allocation never gives them to Stoxkart.

Stoxkart's broadcast websocket streams only `NSE`, `NFO`, `BSE` and `MCX`. A token the master lists only under `NSECD` or `NCDEX` is answered None, and so is a token the master does not list at all. This program holds a three-row master in a stand-in Redis.

It needs no data store, no network and no broker login.

Notice that the currency future and the NCDEX contract are answered None, as is the token missing from the master, while the MCX future is spelled.

Run it from the project root:

    python examples/unified_broker_interface/utilities/quote_subscriptions/stoxkart/StoxkartQuoteSubscription/example_2_exchanges_the_feed_cannot_stream.py
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


class ExchangesTheFeedCannotStreamExample:
    """Spells instruments on exchanges the broadcast feed does and does not carry.

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
            ],
        }
        master = {
            'NSECD:USDINR26NOVFUT': json.dumps(['NSECD', 3, '1234']),
            'NCDEX:GUARSEED26NOVFUT': json.dumps(['NCDEX', 7, '4100']),
            'MCX:GOLD26DECFUT': json.dumps(['MCX', 5, '565899']),
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
            ('USDINR 26 NOV FUT', 'nse', 'nse_currency_futures', 'future', '1234'),
            ('GUARSEED 26 NOV FUT', 'ncdex', 'ncdex_commodity_futures', 'future', '4100'),
            ('a token missing from the master', 'nse', 'nse_equities', 'security', '999999'),
            ('GOLD 26 DEC FUT', 'mcx', 'mcx_commodity_futures', 'future', '565899'),
        ]
        print('Feed exchanges: NSE, NFO, BSE, MCX')
        for label, exchange, segment, shape, token in rows:
            identity = {
                'exchange': exchange,
                'segment': segment,
                'shape': shape,
            }
            print(f'{label}: {self.spelling.member(identity, token, None)}')


if __name__ == '__main__':
    ExchangesTheFeedCannotStreamExample().run()
